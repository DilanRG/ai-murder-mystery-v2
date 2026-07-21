export const MAX_RECIPE_SEED = Number.MAX_SAFE_INTEGER;

const seedError = () => new Error(
  `Case seed must be a whole number from 0 to ${MAX_RECIPE_SEED}.`,
);

export function parseRecipeSeed(rawValue, randomSeed = () => 0) {
  const raw = String(rawValue ?? '').trim();
  const seed = raw === '' ? randomSeed() : Number(raw);
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > MAX_RECIPE_SEED) {
    throw seedError();
  }
  return seed;
}
