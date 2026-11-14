import { describe, expect, it } from 'vitest'
import { glossary } from './glossary.ts'
import { miniTest } from './miniTests.ts'
import { savingLessons } from './savingLessons.ts'
import { topicsFor } from './topics.ts'

describe('the Learn tab content (#764)', () => {
  it('every topic has a three-question mini-test in EN and FI, each right answer among its options', () => {
    for (const topic of ['money', 'bills', 'saving']) {
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

  it('without an overview: bills and saving topics, no money lessons, no "In your numbers" lines', () => {
    expect(topicsFor(null).map((topic) => topic.id)).toEqual(['bills', 'saving'])
    expect(glossary(null, 'en')).toHaveLength(12)
    expect(glossary(null, 'fi').every((entry) => entry.figure === null)).toBe(true)
    expect(savingLessons(null, 'en').every((lesson) => lesson.example === null)).toBe(true)
  })

  it('formats no number and keeps no storage in the content files', async () => {
    const sources = await Promise.all([
      import('./glossary.ts?raw'),
      import('./savingLessons.ts?raw'),
      import('./billLessons.ts?raw'),
      import('./miniTests.ts?raw'),
    ])
    for (const { default: source } of sources) {
      expect(source).not.toMatch(/toFixed|NumberFormat|toLocaleString|localStorage|sessionStorage/)
    }
  })
})
