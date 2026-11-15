import type { Language } from '../api/types.ts'
import type { Opening } from '../lib/openingContext.ts'
import { clientTurnRequest, clientTurns } from './clientTurns.tsx'

/**
 * The composer's paperclip (#705): the bill turn's name and its push, through the same path as the
 * opening's chip (one bill turn; a second tap brings it back). Null where the bill chip is hidden
 * (a live build without the core's bills) or outside the thread.
 */
export function composerBillAction(opening: Pick<Opening, 'pushClientTurn'> | null, lang: Language) {
  const bill = clientTurns.bill
  if (!opening || !bill?.visible()) return null
  return { label: bill.chip(lang), onPress: () => opening.pushClientTurn(clientTurnRequest('bill', lang)) }
}
