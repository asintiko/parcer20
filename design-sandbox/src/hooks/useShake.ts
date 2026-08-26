import { useCallback, useState } from 'react';

/**
 * Trigger CSS shake animation on demand (only on submit, not on every keystroke).
 * Returns [shakeKey, fire].
 *
 * Usage:
 *   const [shakeKey, fire] = useShake();
 *   <input className={errors.x ? 'has-error' : ''} key={shakeKey} />
 *   onSubmit: if (invalid) fire();
 */
export function useShake(): [number, () => void] {
    const [key, setKey] = useState(0);
    const fire = useCallback(() => setKey((k) => k + 1), []);
    return [key, fire];
}
