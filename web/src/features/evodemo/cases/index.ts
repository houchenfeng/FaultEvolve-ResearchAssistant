import { KGTE_CASE } from './kgte';
import { PAPER_CASE } from './paper';
import type { CaseId, DemoCase } from './types';

export const CASES: Record<CaseId, DemoCase> = { paper: PAPER_CASE, kgte: KGTE_CASE };

export const DEFAULT_CASE = PAPER_CASE;

/** 以论文为初始解走论文组合案例，其余初始解都走 KGTE 进化回放。 */
export function caseForSeed(seed: string): DemoCase {
  return seed === PAPER_CASE.seed ? PAPER_CASE : KGTE_CASE;
}
