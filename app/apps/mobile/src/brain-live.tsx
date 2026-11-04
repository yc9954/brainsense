import { View } from "react-native";
import { BrainFrames, BrainMap } from "./brain-map";
import type { VertexTs } from "./brainsense-api";

/** Native fallback for the live cortex: rendered frames (or the schematic map). Web uses three.js. */
export function BrainLive({
  series,
  frames,
}: {
  vertexTs?: VertexTs;
  series?: Record<string, number[]>;
  frames?: string[];
  stimulusUri?: string;
  stimulusText?: string;
  kind?: string;
  height?: number;
}) {
  if (frames?.length) return <BrainFrames frames={frames} series={series} />;
  if (series && Object.keys(series).length) return <BrainMap series={series} />;
  return <View />;
}
