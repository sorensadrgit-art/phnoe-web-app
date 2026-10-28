import React from 'react';
import { Composition } from 'remotion';
import { BIOMECH_HERO_CONFIG } from './compositions/BiomechHeroFilm.mjs';
import { BiomechHeroComposition } from './compositions/BiomechHeroFilm';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id={BIOMECH_HERO_CONFIG.id}
        component={BiomechHeroComposition}
        durationInFrames={BIOMECH_HERO_CONFIG.durationInFrames}
        fps={BIOMECH_HERO_CONFIG.fps}
        width={BIOMECH_HERO_CONFIG.width}
        height={BIOMECH_HERO_CONFIG.height}
        defaultProps={{
          clientName: 'Soren Sadr Portfolio',
          theme: 'dark-luxury'
        }}
      />
    </>
  );
};

export default RemotionRoot;
