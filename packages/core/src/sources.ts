import type { CollectRequest, SupplyBody } from '@bi/contract';

/**
 * Where the BI finds the data for a request. Each source says which requests it can answer (usually by `query.metric` or the
 * `endpoint` name) and answers with a supply. None is registered yet: the governed metric layer, the warehouse and the source
 * systems come next. A source NEVER invents values: no data means no supply.
 */
export interface Source {
  name: string;
  canAnswer(req: CollectRequest): boolean;
  answer(req: CollectRequest): Promise<SupplyBody>;
}

export class SourceRegistry {
  constructor(private readonly sources: Source[] = []) {}
  find(req: CollectRequest): Source | undefined {
    return this.sources.find((s) => s.canAnswer(req));
  }
}
