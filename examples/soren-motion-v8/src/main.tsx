import {createRoot} from 'react-dom/client';
import {MotionConfig} from 'motion/react';
import {ResumeExperience} from './resume/ResumeExperience';
createRoot(document.getElementById('root')!).render(<MotionConfig reducedMotion="user"><ResumeExperience/></MotionConfig>);
