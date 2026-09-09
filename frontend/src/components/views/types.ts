export type Call = (label: string, fn: () => Promise<unknown>) => Promise<void>;
