import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import { OpeningContext, type Opening } from '../lib/openingContext.ts'
import type { ClientTurn } from '../lib/thread.ts'
import { TurnView } from './AnswerView.tsx'
import { clientTurns, openingChips, type ClientTurnProps } from './clientTurns.tsx'
import { OpeningChips } from './OpeningChips.tsx'

function Probe({ turnId }: ClientTurnProps) {
  return (
    <h3 data-step-heading tabIndex={-1}>
      Probe step of turn {turnId}
    </h3>
  )
}

const turn: ClientTurn = { kind: 'client', id: 7, key: 'probe', question: 'Show Sentti a probe', render: 'probe' }
const render = (shown: ClientTurn, latest = true) =>
  renderToStaticMarkup(<TurnView turn={shown} latest={latest} suggestions={[]} onAsk={() => {}} onRetry={() => {}} />)

describe('a client turn in the thread (#319)', () => {
  afterEach(() => {
    delete clientTurns.probe
  })

  it('shows the chip as the user bubble, Sentti without the AI tag, then the registered component', () => {
    clientTurns.probe = { chip: () => 'Show Sentti a probe', visible: () => true, Component: Probe }
    const html = render(turn)
    expect(html).toContain('data-turn="7"')
    expect(html).toContain('data-client-turn="probe"')
    const bubble = html.indexOf('Show Sentti a probe')
    const label = html.indexOf('>Sentti<')
    const step = html.indexOf('Probe step of turn 7')
    expect(bubble).toBeGreaterThan(-1)
    expect(label).toBeGreaterThan(bubble)
    expect(step).toBeGreaterThan(label)
    expect(html).not.toContain('>AI<')
  })

  it('has its own status region, is not busy at first, and has no speaker, stages or retry, latest or not', () => {
    clientTurns.probe = { chip: () => 'Show Sentti a probe', visible: () => true, Component: Probe }
    for (const latest of [true, false]) {
      const html = render(turn, latest)
      expect(html.match(/role="status"/g)).toHaveLength(1)
      expect(html).toContain('aria-busy="false"')
      expect(html.match(/<button/g)).toBeNull()
    }
  })

  it('shows only the bubble and the label for a key the registry does not know', () => {
    const html = render({ ...turn, render: 'unknown' })
    expect(html).toContain('Show Sentti a probe')
    expect(html).toContain('>Sentti<')
    expect(html).not.toContain('Probe step')
  })
})

describe('the opening\'s client-turn chips (#319)', () => {
  const opening = { pushClientTurn: () => {} } as unknown as Opening
  const chips = () =>
    renderToStaticMarkup(
      <OpeningContext.Provider value={opening}>
        <OpeningChips />
      </OpeningContext.Provider>,
    )

  const registered = [...openingChips]
  afterEach(() => {
    delete clientTurns.probe
    openingChips.splice(0, openingChips.length, ...registered)
  })

  it('shows "Show Sentti a bill" in a mock build (#332), apart from the question chips', () => {
    expect(openingChips).toEqual(['bill'])
    const html = chips()
    expect(html).toContain('data-opening-part="client-chips"')
    expect(html).toContain('>Show Sentti a bill</button>')
  })

  it('shows a visible chip and hides one that is not visible', () => {
    openingChips.splice(0, openingChips.length, 'probe')
    clientTurns.probe = { chip: (lang) => (lang === 'fi' ? 'Näytä koe' : 'Show a probe'), visible: () => true, Component: Probe }
    const html = chips()
    expect(html).toContain('data-opening-part="client-chips"')
    expect(html).toContain('>Show a probe</button>')
    clientTurns.probe = { ...clientTurns.probe, visible: () => false }
    expect(chips()).toBe('')
  })
})
