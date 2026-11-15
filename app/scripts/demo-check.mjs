// Headless check of the demo path: the 60-second path of docs/demo-script.md, step by step (#491).
//   npm run demo:check -- <base-url> [--lang en|fi] [--persona CUST00860]
// It drives a local Chrome or chrome-headless-shell through playwright-core (it never downloads a
// browser; set DEMO_CHECK_BROWSER=<path> to pick one) and prints one line per step: PASS or FAIL with
// what it measured, or SKIP with the issue that builds the missing part. Exit code 0 only without FAIL.
// It writes nothing but this output. Never run it in a loop against the dev host: each run asks the
// coach two questions.
import { chromium } from 'playwright-core'
import { CHIP_ROW, TEXT, USAGE, downOnly, findBrowser, line, parseAmount, parseArgs, rowProblems, rowQuestions } from './demo-check-lib.mjs'

// The greeting and the amounts are API texts: Finnish from a live core with lang=fi, English in a
// mock build (its examples are English only), so either form is accepted.
const GREETING = /^(Hi|Hei)\b/
const amount = (text) => parseAmount(text, lang) ?? parseAmount(text, lang === 'fi' ? 'en' : 'fi')
const ANSWER_MS = 60_000 // a live answer from the model can take a while
const MODULE_MS = 30_000
const NEEDED_MS = 8_000 // the label answer, then the count, on a slow host
const STEPS = 6
// A drifting row holds its chips twice; the second copy is aria-hidden and not counted.
const CHIP_BUTTONS = 'button:not([aria-hidden="true"] *)'

const args = parseArgs(process.argv.slice(2))
if (args.error) {
  console.error(`demo:check: ${args.error}\n${USAGE}`)
  process.exit(2)
}
const { base, lang, persona } = args
const T = TEXT[lang]
const executablePath = findBrowser()
if (!executablePath) {
  console.error(
    'demo:check: no Chrome or chrome-headless-shell found. Install Google Chrome, or set DEMO_CHECK_BROWSER=<path to a Chromium>. This check never downloads a browser.',
  )
  process.exit(2)
}

const results = []
const report = (n, status, text) => {
  results.push(status)
  console.log(line(n, status, text))
}
const short = (text, max = 60) => {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim()
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
}

console.log(`Sentti demo check · ${base} · ${lang} · ${persona}`)
let browser
try {
  browser = await chromium.launch({ headless: true, executablePath })
} catch (error) {
  console.error(
    `demo:check: could not start the browser at ${executablePath}: ${short(error.message.split('\n')[0], 160)}. DEMO_CHECK_BROWSER must point at Chrome, Chromium or chrome-headless-shell.`,
  )
  process.exit(2)
}
let context
let page
const pageErrors = []

/** The module's frame after the demo frame opened it (Start over), or the page itself without a frame. */
async function openModule(hasFrame) {
  if (!hasFrame) {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(`${base}/?persona=${persona}&lang=${lang}`)
    return page.mainFrame()
  }
  await page.locator('.start-over').click()
  await page.waitForFunction(
    () => {
      const frame = document.querySelector('iframe.module')
      try {
        return Boolean(frame && frame.contentWindow.location.search.includes('host=demo') && frame.contentDocument.readyState === 'complete')
      } catch {
        return false
      }
    },
    null,
    { timeout: MODULE_MS },
  )
  return (await page.$('iframe.module')).contentFrame()
}

/** Asks by tapping the chip with this text, or by typing it into the composer. Returns the answer's `article`. */
async function ask(mod, question) {
  const before = await mod.locator('article[data-turn]').count()
  // A chip outside the folded opening: after the first answer the opening's chips are inert (out of reach).
  const chip = mod.getByRole('button', { name: question, exact: true }).and(mod.locator('button:not([inert] *)'))
  let how = 'chip'
  if (await chip.count()) {
    // The opening's chip rows drift: a touch on the row stops it (as a finger does), so the chip holds still
    // for the click. The row is brought to the middle first: in the demo frame it may sit under the composer.
    const row = chip.last().locator('xpath=ancestor::*[@data-chip-row][1]')
    if (await row.count()) {
      await row.evaluate((el) => el.scrollIntoView({ block: 'center' }))
      await row.dispatchEvent('pointerdown')
    }
    await chip.last().click()
  }
  else {
    how = 'composer'
    await mod.locator('#chat-input').fill(question)
    await mod.locator('#chat-input').press('Enter')
  }
  const article = mod.locator('article[data-turn]').nth(before)
  await article.waitFor({ timeout: MODULE_MS })
  const started = Date.now()
  let streamed = (await article.getAttribute('aria-busy')) === 'true'
  while ((await article.getAttribute('aria-busy')) !== 'false') {
    if (Date.now() - started > ANSWER_MS) throw new Error(`no finished answer after ${ANSWER_MS / 1000} s`)
    streamed = true
    await mod.waitForTimeout(100)
  }
  return { article, how, streamed, seconds: ((Date.now() - started) / 1000).toFixed(1) }
}

let hasFrame = false
let mod = null
let mock = false
try {
  context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: lang === 'fi' ? 'fi-FI' : 'en-GB' })
  page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(short(error.message, 120)))
  // 1. The demo frame.
  const response = await page.goto(`${base}/demo.html?lang=${lang}&persona=${persona}`)
  await page.waitForSelector('.start-over, #root', { timeout: MODULE_MS }).catch(() => null)
  hasFrame = (await page.locator('.start-over').count()) > 0 && (await page.locator('.row-card').count()) > 0
  if (hasFrame) {
    report(1, 'PASS', `/demo.html is the demo frame: "${short(await page.title())}", host home, Start over, message log`)
  } else if (await page.locator('#root').count()) {
    report(1, 'FAIL', '/demo.html answers with the module (index.html), not the demo frame: the host serves an old build. Redeploy (#442). Steps 2–4 run on the module itself; 5–6 need the frame.')
  } else {
    report(1, 'FAIL', `/demo.html did not load (HTTP ${response?.status() ?? 'none'}). Is ${base} up?`)
    throw new Error('stop')
  }

  // 2. The first screen (60-second path, step 1).
  mod = await openModule(hasFrame)
  await mod.locator('[data-turn="opening"], [data-opening-part="hero"], main').first().waitFor({ timeout: MODULE_MS })
  await mod.locator('[data-opening-part="hero"]').waitFor({ timeout: MODULE_MS }).catch(() => null)
  mock = (await mod.getByText(T.mockBadge).count()) > 0
  const hasOpening = (await mod.locator('[data-turn="opening"]').count()) > 0
  if (!hasOpening) {
    report(2, 'SKIP', 'the opening turn is not in this build (#311, #313)')
  } else {
    const opening = mod.locator('[data-turn="opening"]')
    const greeting = ((await opening.innerText()).split('\n').find((l) => l.trim()) ?? '').trim()
    const hero = (await mod.locator('[data-opening-part="hero"] button span').first().textContent().catch(() => '')) ?? ''
    const review = mod.locator('[data-opening-part="review"]')
    const asks = (await review.count()) > 0 && (await review.first().innerText()).includes(T.asks)
    // The opening's chips are one scrollable row since #784; its question chips are checked here.
    const chips = rowQuestions(await mod.locator(CHIP_ROW).locator(CHIP_BUTTONS).allInnerTexts())
    // The fit at 375 × 768, on the module itself: the row's first chip is above the composer and on screen.
    const fitPage = await context.newPage()
    await fitPage.setViewportSize({ width: 375, height: 768 })
    await fitPage.goto(`${base}/?persona=${persona}&lang=${lang}`)
    await fitPage.locator('[data-opening-part="hero"]').waitFor({ timeout: MODULE_MS }).catch(() => null)
    await fitPage.waitForTimeout(500)
    const fit = await fitPage.evaluate((row) => {
      const first = document.querySelector(row)?.querySelector('button')
      const composer = document.querySelector('form')
      if (!first || !composer) return null
      const box = first.getBoundingClientRect()
      return { chip: Math.round(box.bottom), composer: Math.round(composer.getBoundingClientRect().top), onScreen: box.left >= 0 && box.right <= innerWidth }
    }, CHIP_ROW)
    await fitPage.close()
    const problems = []
    if (!GREETING.test(greeting)) problems.push(`greeting "${short(greeting, 30)}"`)
    if (amount(hero) === null) problems.push(`hero "${short(hero, 20)}" is not an amount`)
    if (!asks) problems.push(`no "${T.asks}" (answered already? Start over resets the viewer)`)
    problems.push(...rowProblems(chips, T.firstQuestion))
    if (!fit) problems.push('no chip row or no composer at 375×768')
    else if (fit.chip > fit.composer) problems.push(`the chip row ends at ${fit.chip} px, under the composer at ${fit.composer} px (375×768)`)
    else if (!fit.onScreen) problems.push('the row\'s first chip is off screen (375×768)')
    const measured = `"${short(greeting, 20)}", hero ${hero}, "${T.asks}" ${asks ? 'shown' : 'missing'}, ${chips.length} question chips in the row, first "${short(chips[0] ?? '?', 30)}"; the row ends ${fit?.chip ?? '?'} px, the composer starts at ${fit?.composer ?? '?'} px (375×768)`
    report(2, problems.length ? 'FAIL' : 'PASS', problems.length ? `${problems.join('; ')} — ${measured}` : `first screen: ${measured}`)
  }

  // 3. Needed: the hero counts down, the page does not scroll, Undo appears.
  const review = mod.locator('[data-opening-part="review"]')
  const needed = review.getByRole('button', { name: T.needed })
  if (!hasOpening) {
    report(3, 'SKIP', 'the review question of the opening turn is not in this build (#311, #313)')
  } else if (!(await review.count()) || !(await needed.count())) {
    report(3, 'FAIL', `no "${T.asks}" question with an answer button to tap`)
  } else {
    // [hero text, scrollY, Undo shown]
    const heroText = () =>
      mod.evaluate((undoSource) => {
        const undo = new RegExp(undoSource)
        return [
          document.querySelector('[data-opening-part="hero"] button span')?.textContent ?? '',
          Math.round(window.scrollY),
          [...document.querySelectorAll('button')].some((b) => undo.test((b.textContent ?? '').trim())),
        ]
      }, T.undo.source)
    // The count starts only after POST /api/baskets/label answers (a live host may be slow); a mock
    // build answers in the page, so Undo or the first changed amount also mean the answer is in.
    let answered = false
    let labelStatus = null
    page
      .waitForResponse((r) => r.url().includes('/api/baskets/label') && r.request().method() === 'POST', { timeout: NEEDED_MS })
      .then((r) => {
        answered = true
        labelStatus = r.status()
      }, () => {})
    const samples = [await heroText()]
    await needed.first().click()
    let still = 0
    const started = Date.now()
    while (Date.now() - started < NEEDED_MS) {
      await mod.waitForTimeout(50)
      const sample = await heroText()
      if (sample[2] || sample[0] !== samples[0][0]) answered = true
      still = answered && sample[0] === samples[samples.length - 1][0] ? still + 1 : 0
      samples.push(sample)
      if (still >= 12) break
    }
    const values = samples.map(([text]) => amount(text)).filter((v) => v !== null)
    const count = downOnly(values)
    const maxScroll = Math.max(...samples.map(([, y]) => y))
    const undo = samples.some(([, , shown]) => shown)
    const shown = (v) => samples.find(([text]) => amount(text) === v)?.[0] ?? String(v)
    const problems = []
    if (!count.ok) problems.push(count.upAt > 0 ? 'the hero went up during the count' : 'the hero did not go down')
    if (maxScroll !== 0) problems.push(`scrollY reached ${maxScroll}`)
    if (!undo) problems.push('no Undo')
    if (!answered) problems.push(`no answer to "${T.needed.source}" within ${NEEDED_MS / 1000} s`)
    if (labelStatus !== null && labelStatus >= 400) problems.push(`POST /api/baskets/label answered ${labelStatus}`)
    const waited = ((Date.now() - started) / 1000).toFixed(1)
    const measured = `${shown(count.from)} → ${shown(count.to)} in ${count.steps} steps${count.upAt === -1 ? ', never up' : ''}; scrollY max ${maxScroll}; Undo ${undo ? 'shown' : 'missing'}; ${waited} s`
    report(3, problems.length ? 'FAIL' : 'PASS', problems.length ? `${problems.join('; ')} — ${measured}` : `Needed: ${measured}`)
  }

  // 4. The chip "Where did my money go?": an answer streams in and ends with text and a card.
  {
    // The question chips of the opening's row (#784).
    const chipNames = rowQuestions(await mod.locator(CHIP_ROW).locator(CHIP_BUTTONS).allInnerTexts())
    const question = chipNames.includes(T.firstQuestion) ? T.firstQuestion : chipNames[0]
    if (!hasOpening || !question) {
      report(4, 'SKIP', 'the question chips of the opening turn are not in this build (#313)')
    } else {
      const answer = await ask(mod, question)
      const texts = await answer.article.locator('p').evaluateAll((ps) => ps.filter((p) => !p.className.includes('ml-auto') && !p.className.includes('sr-only')).map((p) => p.innerText.trim()).filter(Boolean))
      const cards = await answer.article.locator('section').count()
      const text = texts.sort((a, b) => b.length - a.length)[0] ?? ''
      const problems = []
      if (!answer.streamed) problems.push('it did not stream')
      if (!text) problems.push('no text')
      if (!cards) problems.push('no card')
      const which = question === T.firstQuestion ? `"${question}"` : `the first chip "${short(question, 40)}" (no "${T.firstQuestion}" chip)`
      const measured = `${which}: streamed in ${answer.seconds} s, text "${short(text, 50)}", ${cards} card${cards === 1 ? '' : 's'}`
      report(4, problems.length ? 'FAIL' : 'PASS', problems.length ? `${problems.join('; ')} — ${measured}` : measured)
    }
  }

  // 5. "How could I save more?", then "See monthly saving": the frame's host sheet and its log.
  if (!hasFrame) {
    // Without the frame there is no host sheet to check, so no question is spent on it.
    report(5, 'SKIP', 'the host sheet and the message log are part of the demo frame (#442)')
  } else {
    const answer = await ask(mod, T.saveQuestion)
    const action = answer.article.getByRole('button', { name: T.saveAction })
    if (!(await action.count())) {
      if (mock) report(5, 'SKIP', `"${T.saveQuestion}" (${answer.how}): the mock build answers without the safe-to-save card, so there is no "See monthly saving" (#495)`)
      else {
        const buttons = (await answer.article.getByRole('button').allInnerTexts()).map((b) => short(b, 40)).filter((b) => !/\d/.test(b))
        report(5, 'FAIL', `"${T.saveQuestion}" (${answer.how}): the answer has no "See monthly saving" action (its buttons: ${buttons.join(' | ') || 'none'})`)
      }
    } else {
      const label = short(await action.first().innerText(), 50)
      await action.first().click()
      const sheet = await page.locator('.sheet-title').first().waitFor({ timeout: 3000 }).then(() => page.locator('.sheet-title').first().innerText(), () => '')
      const names = await page.locator('.log-item .log-name').allInnerTexts()
      const bodies = await page.locator('.log-item').evaluateAll((items) =>
        items.filter((i) => i.querySelector('.log-name')?.textContent === 'sentti.openHostScreen').map((i) => i.querySelector('.log-body')?.textContent ?? ''),
      )
      const problems = []
      if (!T.hostScreen.test(sheet)) problems.push(sheet ? `host sheet "${short(sheet)}"` : 'no host sheet')
      if (!names.includes('sentti.openHostScreen')) problems.push('the log has no sentti.openHostScreen')
      else if (!bodies.some((b) => b.includes('"monthly_saving"'))) problems.push(`sentti.openHostScreen without the target monthly_saving (${short(bodies[0], 60)})`)
      const measured = `"${label}" → host sheet "${short(sheet)}"; log: ${names.slice(0, 3).join(', ') || 'empty'}`
      report(5, problems.length ? 'FAIL' : 'PASS', problems.length ? `${problems.join('; ')} — ${measured}` : measured)
      await page.keyboard.press('Escape')
    }
  }

  // 6. Start over brings the question back.
  if (!hasFrame) {
    report(6, 'SKIP', 'Start over is part of the demo frame (#442)')
  } else {
    mod = await openModule(true)
    const back = await mod.locator('[data-opening-part="review"]').getByRole('button', { name: T.needed }).first().waitFor({ timeout: MODULE_MS }).then(() => true, () => false)
    const logLeft = await page.locator('.log-item').count()
    report(6, back ? 'PASS' : 'FAIL', back ? `Start over: "${T.asks}" is back with its answers; message log ${logLeft ? `has ${logLeft} item(s)` : 'empty'}` : `after Start over there is no "${T.asks}" question`)
  }
} catch (error) {
  if (error.message !== 'stop') {
    const step = results.length + 1
    report(step, 'FAIL', `stopped: ${short(error.message.split('\n')[0], 140)}`)
  }
  for (let step = results.length + 1; step <= STEPS; step++) report(step, 'SKIP', 'not reached')
} finally {
  await browser.close()
}

const count = (status) => results.filter((r) => r === status).length
if (pageErrors.length) console.log(`page errors: ${pageErrors.slice(0, 3).join(' | ')}`)
console.log(`Result: ${count('PASS')} PASS, ${count('SKIP')} SKIP, ${count('FAIL')} FAIL${mock ? ' (mock build)' : ''}`)
process.exit(count('FAIL') ? 1 : 0)
