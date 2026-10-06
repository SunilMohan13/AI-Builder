export function createSeededRandom(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0xffffffff
  }
}

/**
 * Position-addressable noise. Unlike a sequential PRNG this returns the same
 * value for the same cell regardless of iteration order, so the grid can be
 * generated per viewport instead of materialised up front.
 */
export function hashNoise(x: number, y: number, seed = 42): number {
  let h = (x * 374761393 + y * 668265263 + seed * 1274126177) >>> 0
  h = (h ^ (h >>> 13)) >>> 0
  h = Math.imul(h, 1274126177) >>> 0
  h = (h ^ (h >>> 16)) >>> 0
  return h / 0xffffffff
}
