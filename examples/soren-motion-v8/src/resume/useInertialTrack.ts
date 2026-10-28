import * as React from 'react';
import {referenceTrack} from './reference-motion.mjs';
export function useInertialTrack(config: Parameters<typeof referenceTrack>[1]) {
  return referenceTrack(React, config);
}
