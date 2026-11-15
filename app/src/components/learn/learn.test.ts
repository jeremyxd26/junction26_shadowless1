import { describe, expect, it } from 'vitest'
import { glossary } from './glossary.ts'
import { miniTest } from './miniTests.ts'
import { teachLessons } from './teachLessons.ts'
import { topicsFor } from './topics.ts'

describe('the Learn tab content (#764)', () => {
  it('every topic has a three-question mini-test in EN and FI, each right answer among its options', () => {
    for (const topic of ['money', 'bills', 'saving', 'compare']) {
      for (const lang of ['en', 'fi'] as const) {
        const test = miniTest(topic, lang)
        expect(test).toHaveLength(3)
        for (const question of test) {
          expect(question.options.map((option) => option.key)).toContain(question.right)
          expect(question.explain.length).toBeGreaterThan(10)
        }
      }
      expect(miniTest(topic, 'fi').map((q) => q.right)).toEqual(miniTest(topic, 'en').map((q) => q.right))
    }
  })

  it('without an overview: every topic, no numbers cards, no "In your numbers" lines', () => {
    expect(topicsFor(null).map((topic) => topic.id)).toEqual(['money', 'bills', 'saving', 'compare'])
    expect(['money', 'saving'].flatMap((topic) => teachLessons(topic, null, 'en')).every((lesson) => lesson.numbers.length === 0)).toBe(true)
    expect(glossary(null, 'en')).toHaveLength(12)
    expect(glossary(null, 'fi').every((entry) => entry.figure === null)).toBe(true)
  })

  it('formats no number and keeps no storage in the content files', async () => {
    const sources = await Promise.all([
      import('./glossary.ts?raw'),
      import('./teachLessons.ts?raw'),
      import('./miniTests.ts?raw'),
    ])
    for (const { default: source } of sources) {
      expect(source).not.toMatch(/toFixed|NumberFormat|toLocaleString|localStorage|sessionStorage/)
    }
  })

  it('every lesson teaches in four steps, EN and FI alike, its check answer among the options, and says left to spend', () => {
    for (const topic of ['money', 'bills', 'saving', 'compare']) {
      const en = teachLessons(topic, null, 'en')
      const fi = teachLessons(topic, null, 'fi')
      expect(fi.map((lesson) => lesson.key)).toEqual(en.map((lesson) => lesson.key))
      for (const lesson of [...en, ...fi]) {
        expect(lesson.teach.length).toBeGreaterThan(40)
        expect(lesson.check.options.map((option) => option.key)).toContain(lesson.check.right)
        expect(lesson.takeaway.length).toBeGreaterThan(10)
        expect(`${lesson.title} ${lesson.teach} ${lesson.takeaway}`).not.toMatch(/safe to spend|safely spend|turvallisesti/i)
      }
    }
  })
})
