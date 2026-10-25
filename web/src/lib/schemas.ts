// Контракт API песочницы (api/dto.py, docs/dashboard-igor-spec.md §9.3). Ответ вне контракта — ошибка, а не тихий
// мусор на экране.
import { z } from 'zod';

const flag = z.union([z.boolean(), z.number()]).transform(Boolean);

export const OutcomeSchema = z.enum(['APPROVE', 'COUNTER', 'REQUEST_INFO', 'REJECT']);
export type Outcome = z.infer<typeof OutcomeSchema>;

const CodeSchema = z.object({
  code: z.string(),
  category: z.string(),
  loss: z.number().nullable().optional(),
  factors: z.array(z.string()).optional(),
});
export type Code = z.infer<typeof CodeSchema>;

export const LeversSchema = z.object({
  product: z.string(),
  requested_amount: z.number(),
  requested_term_m: z.number(),
  has_rko: flag,
  bank_turnover_month_rub: z.number(),
  guarantee: flag,
  marketplace: flag,
  insurance: flag,
  subscription: flag,
  bki_consent: flag,
});
export type Levers = z.infer<typeof LeversSchema>;

export const PricingSchema = z.object({
  funding: z.number(),
  el: z.number(),
  capital: z.number(),
  opex: z.number(),
  margin: z.number(),
  discounts: z.number(),
  rate: z.number(),
  lgd: z.number(),
  risk_weight: z.number(),
  irb_class: z.string(),
  lgd_capital: z.number(),
  fee: z.number(),
  insurance_rate: z.number(),
  curve_date: z.string().nullable(),
  all_in: z.number().nullable(),
});
export type Pricing = z.infer<typeof PricingSchema>;

export const EvaluationSchema = z.object({
  inn: z.string(),
  score: z.number(),
  pd: z.number(),
  risk_class: z.number(),
  approval_probability: z.number(),
  approval_score: z.number(),
  approval_mode: z.enum(['full', 'soft']),
  approval_imputed: z.array(z.string()),
  approval_imputed_labels: z.array(z.string()),
  approval_explain: z.array(
    z.object({ feature: z.string(), label: z.string(), category: z.string(), category_label: z.string(), points: z.number() }),
  ),
  outcome: OutcomeSchema,
  product: z.string(),
  offered_product: z.string(),
  requested_amount: z.number(),
  offered_amount: z.number(),
  limit: z.number(),
  requested_term_m: z.number(),
  route: z.object({ from: z.string(), to: z.string(), reasons: z.array(CodeSchema) }).nullable(),
  pricing: PricingSchema.nullable(),
  monthly_payment: z.number().nullable(),
  stop_factors: z.array(CodeSchema),
  reasons: z.array(CodeSchema),
  requests: z.array(z.string()),
  products: z.array(z.object({ product: z.string(), label: z.string(), available: z.boolean(), reasons: z.array(CodeSchema) })),
});
export type Evaluation = z.infer<typeof EvaluationSchema>;

export const PointSchema = z.object({
  x: z.number(),
  approval_probability: z.number(),
  outcome: OutcomeSchema,
  offered_product: z.string(),
  offered_amount: z.number(),
  limit: z.number(),
  binding: z.string().nullable(),
  pd: z.number(),
  rate_requested: z.number(),
  rate: z.number().nullable(),
  all_in: z.number().nullable(),
});
export type Point = z.infer<typeof PointSchema>;

export const SimulationSchema = z.object({
  axis: z.enum(['requested_amount', 'requested_term_m']),
  points: z.array(PointSchema),
  limit: z.number(),
  binding: z.string().nullable(),
  requested: z.number(),
});
export type Simulation = z.infer<typeof SimulationSchema>;

export const ScenarioSchema = z.object({
  key: z.string(),
  title: z.string(),
  outcome: OutcomeSchema,
  offered_product: z.string(),
  offered_amount: z.number(),
  approval_probability: z.number(),
  delta_approval_pp: z.number(),
  pd: z.number(),
  rate: z.number().nullable(),
  all_in: z.number().nullable(),
  delta_rate_pp: z.number().nullable(),
  delta_all_in_pp: z.number().nullable(),
  levers: LeversSchema,
});
export type Scenario = z.infer<typeof ScenarioSchema>;

export const WhatIfSchema = z.object({ base: EvaluationSchema, scenarios: z.array(ScenarioSchema) });
export type WhatIf = z.infer<typeof WhatIfSchema>;

export const ProductSchema = z.object({
  product: z.string(),
  label: z.string(),
  min_amount: z.number(),
  max_amount: z.number(),
  min_age_months: z.number(),
  requires: z.array(z.string()),
  revolving: z.boolean(),
});
export type Product = z.infer<typeof ProductSchema>;

export const MetaSchema = z.object({
  products: z.array(ProductSchema),
  codes: z.array(z.object({ code: z.string(), group: z.string(), category: z.string() })),
  features: z.record(z.string(), z.string()),
  min_dscr: z.number(),
  round_to: z.number(),
  asof: z.string(),
  pricing_note: z.string(),
});
export type Meta = z.infer<typeof MetaSchema>;

export const PersonaCardSchema = z.object({
  id: z.string(),
  name: z.string(),
  inn: z.string(),
  tagline: z.string(),
  story: z.string(),
  okved_name: z.string(),
  okved: z.string(),
});
export type PersonaCard = z.infer<typeof PersonaCardSchema>;

export const PersonaSchema = PersonaCardSchema.extend({
  facts: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      value: z.union([z.number(), z.string()]),
      unit: z.enum(['rub', 'pct', 'months', 'days']),
      source: z.string(),
    }),
  ),
  levers: LeversSchema,
});
export type Persona = z.infer<typeof PersonaSchema>;

// ---- Кредитный конвейер (docs/specs/2026-10-25-conveyor.md, раздел Contract). Неизвестные поля пропускаем.
const RCode = z.looseObject({ code: z.string(), category: z.string() });
const PartialLevers = LeversSchema.partial();

export const LoginSchema = z.looseObject({ token: z.string(), role: z.enum(['client', 'analyst']), name: z.string() });
export type Login = z.infer<typeof LoginSchema>;

export const CompanySchema = z.looseObject({
  persona_id: z.string(),
  name: z.string(),
  inn: z.string(),
  ogrn: z.string().optional(),
  okved: z.string(),
  okved_name: z.string(),
  status: z.string(),
  status_label: z.string().optional(),
  registered: z.string().optional(),
  age_months: z.number(),
  address: z.string().optional(),
  director_role: z.string().optional(),
  sources: z.array(z.looseObject({ name: z.string(), asof: z.string() })),
});
export type Company = z.infer<typeof CompanySchema>;

export const NewsSchema = z.looseObject({
  id: z.union([z.string(), z.number()]),
  date: z.string(),
  tag: z.string(),
  title: z.string(),
  body: z.string(),
  why: z.string(),
  action: z.looseObject({ label: z.string(), levers: PartialLevers.nullable().optional() }).nullable(),
});
export type News = z.infer<typeof NewsSchema>;

const Turn = z.enum(['client', 'bank']).nullable();
const CompanyRef = z.looseObject({ name: z.string(), inn: z.string() });

export const AppSummarySchema = z.looseObject({
  id: z.string(),
  company: CompanyRef,
  product_label: z.string(),
  amount: z.number(),
  term_m: z.number(),
  status: z.string(),
  status_label: z.string(),
  whose_turn: Turn,
  updated_at: z.string(),
  route_reason: z.string().nullable().optional(),
});
export type AppSummary = z.infer<typeof AppSummarySchema>;

export const ApplicationSchema = z.looseObject({
  id: z.string(),
  persona_id: z.string(),
  company: CompanyRef,
  product: z.string(),
  product_label: z.string(),
  levers: LeversSchema,
  purpose: z.string(),
  status: z.string(),
  status_label: z.string(),
  whose_turn: Turn,
  next_step: z.string(),
  steps: z.array(z.looseObject({ status: z.string(), label: z.string(), state: z.enum(['done', 'current', 'todo']) })),
  created_at: z.string(),
  updated_at: z.string(),
  decision: z
    .looseObject({
      outcome: OutcomeSchema,
      title: z.string(),
      reasons: z.array(RCode),
      requests: z.array(z.string()),
      route: z.looseObject({ from: z.string(), to: z.string(), reasons: z.array(RCode) }).nullable().optional(),
      by: z.enum(['system', 'analyst']),
      note: z.string().nullable(),
    })
    .nullable(),
  offer: z
    .looseObject({
      product: z.string(),
      product_label: z.string(),
      amount: z.number(),
      term_m: z.number().nullable(), // у карты и овердрафта срока нет
      rate: z.number().nullable(),
      all_in: z.number().nullable(),
      monthly_payment: z.number().nullable(),
    })
    .nullable(),
  documents: z.array(z.looseObject({ name: z.string(), status: z.enum(['requested', 'uploaded']) })),
  sign_code: z.string().nullable().optional(),
  loan: z
    .looseObject({
      number: z.string(),
      amount: z.number(),
      term_m: z.number().nullable(),
      rate: z.number().nullable(),
      monthly_payment: z.number().nullable(),
      issued_at: z.string(),
      account: z.string(),
    })
    .nullable(),
  events: z.array(
    z.looseObject({
      at: z.string(),
      from: z.string().nullable(),
      to: z.string(),
      to_label: z.string(),
      actor: z.enum(['client', 'system', 'analyst']),
      note: z.string().nullable(),
    }),
  ),
  actions: z.array(z.string()),
  risk: z
    .looseObject({
      pd: z.number(),
      risk_class: z.union([z.number(), z.string()]),
      score: z.number(),
      approval_probability: z.number(),
      limit: z.number(),
      stop_factors: z.array(RCode),
      reasons: z.array(RCode),
      route_reason: z.string().nullable(),
      facts: z.array(
        z.looseObject({ key: z.string(), label: z.string(), value: z.union([z.number(), z.string(), z.null()]), unit: z.string().nullable().optional() }),
      ),
    })
    .nullable()
    .optional(),
});
export type Application = z.infer<typeof ApplicationSchema>;

export const ChatReplySchema = z.looseObject({
  reply: z.string(),
  levers: PartialLevers.nullable().optional(),
  mode: z.enum(['llm', 'rules']),
});
export type ChatReply = z.infer<typeof ChatReplySchema>;
