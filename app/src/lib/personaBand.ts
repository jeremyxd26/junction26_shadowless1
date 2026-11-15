/** An age band as the persona picker says it: "35-44" with an en dash, and the bands from 65 up as "65+" (#872). */
export function bandText(band: string): string {
  if (band === '65-74' || band === '75+') return '65+'
  return band.replace('-', '\u2013')
}
