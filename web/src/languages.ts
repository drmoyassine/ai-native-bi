// Languages (DEC-038, the AMS's registry): English is the interface's primary language; an organization chooses ONE secondary
// language. The registry says how a language is written, so the shell sets <html lang>, <html dir> and the font stack. The server's
// copy is src/bi/languages.py; the list comes from GET /app/api/languages, this file only knows how to apply one.
export type Script =
  | 'latin'
  | 'arabic'
  | 'hebrew'
  | 'cjk-sc'
  | 'cjk-tc'
  | 'cjk-jp'
  | 'cjk-kr'
  | 'devanagari'
  | 'bengali'
  | 'cyrillic'
  | 'greek'
  | 'thai';

export interface LanguageInfo {
  code: string;
  name_en: string;
  native_name: string;
  dir: 'ltr' | 'rtl';
  script: Script;
}

export const PRIMARY_LANGUAGE = 'en';

/** Sets the page's language, direction and font stack (index.css, html[data-script]). */
export function applyLanguage(info: Pick<LanguageInfo, 'code' | 'dir' | 'script'> | null): void {
  const root = document.documentElement;
  root.lang = info?.code ?? PRIMARY_LANGUAGE;
  root.dir = info?.dir ?? 'ltr';
  root.dataset.script = info?.script ?? 'latin';
}

/** The contrast white text reaches on a colour (WCAG); the accent is a button background, so it must reach 4.5. */
export function contrastWithWhite(hex: string): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16)));
  return 1.05 / (0.2126 * r! + 0.7152 * g! + 0.0722 * b! + 0.05);
}

export const isReadableAccent = (hex: string) => /^#[0-9a-fA-F]{6}$/.test(hex) && contrastWithWhite(hex) >= 4.5;

/** Themes buttons and highlights with the organization's accent, or the default when it has none. */
export function applyAccent(accent: string | null | undefined): void {
  const root = document.documentElement;
  if (accent && isReadableAccent(accent)) root.style.setProperty('--primary', accent);
  else root.style.removeProperty('--primary');
}
