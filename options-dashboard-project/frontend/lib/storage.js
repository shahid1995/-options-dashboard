// Safe localStorage JSON helpers (no-ops when storage is unavailable).

export function loadJSON(key, fallback = null) {
  try {
    const saved = window.localStorage.getItem(key);
    return saved ? JSON.parse(saved) : fallback;
  } catch (e) {
    console.warn(`Could not load "${key}" from localStorage:`, e);
    return fallback;
  }
}

export function saveJSON(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    console.warn(`Could not save "${key}" to localStorage:`, e);
  }
}
