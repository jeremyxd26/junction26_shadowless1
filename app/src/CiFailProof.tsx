// Deliberately broken file for the fail-proof of #137. Never merged; the scratch PR is closed.
import { useState } from 'react'

export function CiFailProof({ on }: { on: boolean }) {
  const unused = 1
  if (on) {
    const [value] = useState(0)
    return <p>{value}</p>
  }
  return null
}
