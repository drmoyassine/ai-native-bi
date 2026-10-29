import { describe, expect, it } from 'vitest';
import { contrastWithWhite, isReadableAccent } from './languages';

describe('the accent colour', () => {
  it('must carry white text (WCAG AA, 4.5), as in the AMS', () => {
    expect(contrastWithWhite('#000000')).toBeCloseTo(21, 0);
    expect(isReadableAccent('#1d3557')).toBe(true);
    expect(isReadableAccent('#ffff00')).toBe(false);
    expect(isReadableAccent('red')).toBe(false);
  });
});
