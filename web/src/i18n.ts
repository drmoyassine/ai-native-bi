import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { EN_CATALOGUE } from './locales/en';

// The English catalogue is the source of every string (src/locales/en.ts, flat dotted keys, the AMS's pattern, DEC-038). Anything
// a language lacks falls back to English.
export const i18nReady = i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  keySeparator: false,
  nsSeparator: false,
  load: 'currentOnly',
  interpolation: { escapeValue: false },
  returnNull: false,
  resources: { en: { translation: EN_CATALOGUE } },
});

export { useTranslation } from 'react-i18next';
export default i18n;
