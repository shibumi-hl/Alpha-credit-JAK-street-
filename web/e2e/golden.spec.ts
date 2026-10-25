import { expect, test } from '@playwright/test';

// Золотой путь демо (ТЗ §3.1): Марина без БКИ → согласие → контрпредложение 3,61 млн (L02) → «Взять на 24 месяца» →
// одобрение 6 млн. Числа — с обученного движка на сервере.
test('Марина: от предоценки до одобрения 6 млн', async ({ page }) => {
  await page.goto('/?company=marina');
  const h1 = page.getByRole('heading', { level: 1 });
  await expect(h1).toHaveText('Нужно согласие на запрос в БКИ');
  await expect(page.getByText('предоценка без кредитной истории')).toBeVisible();

  await page.getByRole('button', { name: 'Дать согласие на запрос в БКИ' }).click();
  await expect(h1).toHaveText(/^Можем выдать 3,61\s+млн\s+₽$/);
  await expect(page.getByText(/Денежного потока с запасом DSCR/)).toBeVisible();
  await expect(page.locator('.kpi .t-kpi').nth(1)).toHaveText('19,0%');

  const longer = page.getByRole('article', { name: 'Взять на 24 месяца' });
  await longer.getByRole('button', { name: 'Применить' }).click();
  await expect(h1).toHaveText(/^Одобрим 6\s+млн\s+₽ на 24\s+мес\.$/);
  await expect(page.locator('.kpi .t-kpi').nth(1)).toHaveText('19,7%');

  await page.getByRole('button', { name: 'Отменить' }).click(); // undo возвращает контрпредложение
  await expect(h1).toHaveText(/^Можем выдать 3,61/);
});

test('все демо-компании открываются со своим исходом и без горизонтальной прокрутки', async ({ page }) => {
  const expected: Record<string, RegExp> = {
    bakery: /^Одобрим/,
    young: /бизнес-карта$/,
    docs: /^Нужны документы$/,
    overdue: /^Сейчас не сможем/,
  };
  for (const [id, h] of Object.entries(expected)) {
    await page.goto(`/?company=${id}`);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(h);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, id).toBeLessThanOrEqual(0);
  }
});
