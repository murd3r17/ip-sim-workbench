/** Keep SVG labels inside the canvas and retain an identifiable suffix. */
export function compactTopologyLabel(label: string, pixelBudget: number): string {
  const characters = Array.from(label)
  const width = (items: string[]) => items.reduce((sum, ch) => sum + (ch.codePointAt(0)! > 127 ? 13 : 8), 0)
  if (width(characters) <= pixelBudget) return label
  let side = Math.max(1, Math.floor(characters.length / 2))
  while (side > 1 && width([...characters.slice(0, side), '…', ...characters.slice(-side)]) > pixelBudget) side--
  return characters.slice(0, side).join('') + '…' + characters.slice(-side).join('')
}
