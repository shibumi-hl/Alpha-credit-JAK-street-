"""ИИгорь: правила, инструменты и защита чисел без сетевых запросов."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.igor import make_llm_from_env, reply


@pytest.fixture
def context():
    persona = json.loads(open('demo/personas/marina.json').read())
    levers = {**persona['levers'], 'requested_amount': 2_000_000, 'requested_term_m': 36}
    result = dict(approval_probability=.63, outcome='COUNTER', offered_amount=3_610_000,
                  limit=3_610_000, monthly_payment=330_000, pricing={'rate': .19, 'all_in': .26},
                  reasons=[{'code': 'L02', 'category': 'Денежный поток'}], requests=[], route=None)
    evaluate = Mock(side_effect=lambda x: {**deepcopy(result), 'requested_amount': x['requested_amount'],
                                          'requested_term_m': x['requested_term_m']})
    whatif = Mock(return_value={'base': result, 'scenarios': [
        {'key': 'bad', 'label': 'Не выбирать', 'delta_approval_pp': -1},
        {'key': 'term_24', 'title': 'Взять на 24 месяца', 'delta_approval_pp': 8,
         'levers': {'requested_term_m': 24}}]})
    return persona, levers, evaluate, whatif


def answer(context, text='', llm=None):
    p, levers, evaluate, whatif = context
    return reply(p, levers, [{'role': 'user', 'content': text}], evaluate, whatif, llm)


def message(text=None, calls=None):
    return SimpleNamespace(content=text, tool_calls=calls or [])


def call(name, args, ident='tool-1'):
    return SimpleNamespace(id=ident, type='function',
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def client(*messages):
    create = Mock(side_effect=[SimpleNamespace(choices=[SimpleNamespace(message=m)])
                               if not isinstance(m, Exception) else m for m in messages])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize('text,changes', [
    ('6 млн на закупку на год', {'requested_amount': 6_000_000, 'requested_term_m': 12}),
    ('1,5 млн на полгода', {'requested_amount': 1_500_000, 'requested_term_m': 6}),
    ('500 тыс на 12 месяцев', {'requested_amount': 500_000, 'requested_term_m': 12}),
    ('6000000 на 2 года', {'requested_amount': 6_000_000, 'requested_term_m': 24}),
    ('нужна карта', {'product': 'card'}), ('кредитная линия', {'product': 'credit_line'}),
    ('под залог', {'product': 'secured'}), ('согласен', {'bki_consent': True}),
    ('согласие на БКИ', {'bki_consent': True}), ('не согласен на БКИ', None),
    ('на 12 месяцев', {'requested_term_m': 12}), ('расскажите об условиях', None),
])
def test_rules(context, text, changes):
    before = deepcopy(context[:2])
    r = answer(context, text)
    assert r['levers'] == changes
    assert r['mode'] == 'rules'
    assert '63%' in r['reply'] and '3,61 млн ₽' in r['reply']
    assert '19,0%' in r['reply'] and '26,0%' in r['reply']
    assert 'Денежный поток' in r['reply'] and 'Взять на 24 месяца' in r['reply']
    assert 'предварительная оценка' in r['reply'].lower() and 'не решение банка' in r['reply']
    assert context[:2] == before
    context[2].assert_called_once_with({**context[1], **(changes or {})})
    context[3].assert_called_once_with({**context[1], **(changes or {})})


def test_last_user_only(context):
    p, levers, evaluate, whatif = context
    r = reply(p, levers, [{'role': 'user', 'content': '6 млн'},
                         {'role': 'user', 'content': 'на полгода'},
                         {'role': 'assistant', 'content': '9 млн'}], evaluate, whatif)
    assert r['levers'] == {'requested_term_m': 6}


def test_llm_placeholders(context):
    c = client(message('Шанс {{approval}}, сумма {{offered_amount}}, лимит {{limit}}, '
                       'ставка {{rate}}, ПСК {{all_in}}, платёж {{monthly_payment}}, '
                       'срок {{term}}, запрос {{amount}}.'))
    r = answer(context, llm=(c, 'fake'))
    assert r['mode'] == 'llm' and r['levers'] is None
    for value in ('63%', '3,61 млн ₽', '19,0%', '26,0%', '330 тыс ₽', '36', '2 млн ₽'):
        assert value in r['reply']
    assert 'не решение банка' in r['reply']
    assert c.chat.completions.create.call_args.kwargs['timeout'] == 20


@pytest.mark.parametrize('text', ['6 млн ₽', 'ставка 19%', '500 тыс', 'рост 2 п.п.',
                                 '₽ 600', '{{unknown}}', '{{approval}} и 6 млн ₽'])
def test_guard(context, text):
    assert answer(context, '1,5 млн на полгода', (client(message(text)), 'fake'))['mode'] == 'rules'


@pytest.mark.parametrize('error', [RuntimeError('сбой'), TimeoutError('таймаут')])
def test_llm_error(context, error):
    r = answer(context, '6 млн на год', (client(error), 'fake'))
    assert r['mode'] == 'rules' and r['levers']['requested_amount'] == 6_000_000


def test_tools_use_latest_levers(context):
    c = client(message(calls=[call('set_levers', {'changes': {'requested_amount': 5_000_000}}),
                              call('evaluate', {}, 'tool-2'), call('whatif', {}, 'tool-3')]),
               message('Ваш запрос {{amount}}, шанс {{approval}}.'))
    r = answer(context, llm=(c, 'fake'))
    assert r['mode'] == 'llm' and r['levers'] == {'requested_amount': 5_000_000}
    assert '5 млн ₽' in r['reply']
    assert context[2].call_args.args[0]['requested_amount'] == 5_000_000
    assert context[3].call_args.args[0]['requested_amount'] == 5_000_000
    history = c.chat.completions.create.call_args.kwargs['messages']
    assert len([m for m in history if m['role'] == 'tool']) == 3


@pytest.mark.parametrize('changes', [{'revenue': 123}, {'product': 'invented'},
    {'requested_amount': -1}, {'requested_term_m': 1.5}, {'bki_consent': 'false'},
    {'requested_amount': float('nan')}, {'requested_term_m': True}])
def test_invalid_tools_fall_back(context, changes):
    c = client(message(calls=[call('set_levers', {'changes': changes})]))
    r = answer(context, llm=(c, 'fake'))
    assert r['mode'] == 'rules' and r['levers'] is None


def test_round_limit_and_rollback(context):
    c = client(*[message(calls=[call('set_levers', {'changes': {'requested_amount': 7_000_000}})])] * 3)
    r = answer(context, llm=(c, 'fake'))
    assert r['mode'] == 'rules' and r['levers'] is None
    assert c.chat.completions.create.call_count == 3
    assert context[2].call_args.args[0]['requested_amount'] == 2_000_000


def test_env(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', '')
    assert make_llm_from_env() is None
    constructor = Mock()
    monkeypatch.setattr('openai.OpenAI', constructor)
    monkeypatch.setenv('LLM_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.invalid/v1')
    monkeypatch.setenv('LLM_MODEL', 'demo-model')
    assert make_llm_from_env() == (constructor.return_value, 'demo-model')
    assert constructor.call_args.kwargs == dict(api_key='test-key', base_url='https://example.invalid/v1',
                                                timeout=20, max_retries=0)


def test_unlabelled_scenario_is_readable(context):
    context[3].return_value['scenarios'] = [
        {'key': 'custom', 'delta_approval_pp': 3, 'levers': {'requested_term_m': 24}}]
    text = answer(context)['reply']
    assert '24 мес.' in text and 'requested_term_m' not in text


def test_final_text_uses_evaluation_after_set(context):
    context[2].side_effect = lambda x: dict(approval_probability=x['requested_amount'] / 10_000_000,
                                          outcome='APPROVE', pricing=None)
    c = client(message(calls=[call('set_levers', {'changes': {'requested_amount': 5_000_000}})]),
               message('Шанс {{approval}}, ставка {{rate}}.'))
    r = answer(context, llm=(c, 'fake'))
    assert r['mode'] == 'llm' and '50%' in r['reply'] and 'не рассчитано' in r['reply']


def test_persona_product_list(context):
    context[0]['products'] = [{'product': 'express'}]
    c = client(message(calls=[call('set_levers', {'changes': {'product': 'secured'}})]))
    assert answer(context, llm=(c, 'fake'))['mode'] == 'rules'


def test_no_positive_scenario_or_pricing(context):
    context[2].side_effect = None
    context[2].return_value = dict(approval_probability=0, outcome='REJECT', pricing=None,
                                  offered_amount=0, reasons=[], requests=[])
    context[3].return_value['scenarios'] = [{'delta_approval_pp': 0, 'label': 'Не выбирать'}]
    text = answer(context)['reply']
    assert '0%' in text and '0 ₽' in text and 'Не выбирать' not in text
    assert 'не рассчитано' in text and 'уточнить причины' in text
