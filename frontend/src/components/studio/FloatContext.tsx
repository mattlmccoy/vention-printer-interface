import { createContext, useContext } from "react";
import type { FloatRect, LayoutAction, Section } from "../../lib/layout.ts";

export interface FloatCtx { floating: Partial<Record<Section, FloatRect>>; dispatch: (a: LayoutAction) => void; }
/** Lets any RailSection with an `id` pop out into a floating window (provided by StudioFrame). */
export const FloatContext = createContext<FloatCtx | null>(null);
export function useFloat(): FloatCtx | null { return useContext(FloatContext); }
