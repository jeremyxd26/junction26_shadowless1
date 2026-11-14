// How each basket state looks: icon + label + colour, always together (DESIGN.md section 2.1).
export const BASKETS: Record<string, { icon: string; color: string; tint: string; bar: string; line: string }> = {
  regular_essentials: {
    icon: '🏠',
    color: 'text-basket-essentials',
    tint: 'bg-basket-essentials-tint',
    bar: 'bg-basket-essentials',
    line: 'border-basket-essentials',
  },
  unexpected_necessities: {
    icon: '🔧',
    color: 'text-basket-unexpected',
    tint: 'bg-basket-unexpected-tint',
    bar: 'bg-basket-unexpected',
    line: 'border-basket-unexpected',
  },
  everyday_spending: {
    icon: '☕️',
    color: 'text-basket-everyday',
    tint: 'bg-basket-everyday-tint',
    bar: 'bg-basket-everyday',
    line: 'border-basket-everyday',
  },
  // Waiting for an answer: neutral, a dashed tile and a hatched bar, never a basket colour.
  unclassified: {
    icon: '?',
    color: 'text-waiting',
    tint: 'bg-waiting-tint border-[1.5px] border-dashed border-waiting',
    bar: 'bar-hatched',
    line: 'border-waiting',
  },
}
