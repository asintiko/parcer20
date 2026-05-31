/**
 * Russian noun pluralization.
 *
 * pluralRu(1, ['сообщение', 'сообщения', 'сообщений']) → 'сообщение'
 * pluralRu(3, ['сообщение', 'сообщения', 'сообщений']) → 'сообщения'
 * pluralRu(5, ['сообщение', 'сообщения', 'сообщений']) → 'сообщений'
 */
export function pluralRu(n: number, forms: [string, string, string]): string {
    const abs = Math.abs(Math.trunc(n));
    const mod10 = abs % 10;
    const mod100 = abs % 100;
    if (mod100 >= 11 && mod100 <= 14) return forms[2];
    if (mod10 === 1) return forms[0];
    if (mod10 >= 2 && mod10 <= 4) return forms[1];
    return forms[2];
}

export function pluralRuWith(n: number, forms: [string, string, string]): string {
    return `${n} ${pluralRu(n, forms)}`;
}
