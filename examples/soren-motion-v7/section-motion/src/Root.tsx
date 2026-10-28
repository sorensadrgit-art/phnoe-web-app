import {Composition} from 'remotion';
import {SectionStudy} from './SectionStudy';
import {PremiumStudy} from './PremiumStudies';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="AboutPremium" component={PremiumStudy} defaultProps={{kind:'about'}} durationInFrames={240} fps={30} width={1200} height={704}/>
      <Composition id="ExperiencePremium" component={PremiumStudy} defaultProps={{kind:'experience'}} durationInFrames={240} fps={30} width={1200} height={704}/>
      <Composition id="EducationPremium" component={PremiumStudy} defaultProps={{kind:'education'}} durationInFrames={240} fps={30} width={1200} height={704}/>
      <Composition id="ProjectsPremium" component={PremiumStudy} defaultProps={{kind:'projects'}} durationInFrames={240} fps={30} width={1200} height={704}/>
      <Composition id="About" component={SectionStudy} defaultProps={{kind:'about'}} durationInFrames={180} fps={30} width={1200} height={704}/>
      <Composition id="Experience" component={SectionStudy} defaultProps={{kind:'experience'}} durationInFrames={180} fps={30} width={1200} height={704}/>
      <Composition id="Education" component={SectionStudy} defaultProps={{kind:'education'}} durationInFrames={180} fps={30} width={1200} height={704}/>
      <Composition id="Projects" component={SectionStudy} defaultProps={{kind:'projects'}} durationInFrames={180} fps={30} width={1200} height={704}/>
      <Composition id="Skills" component={SectionStudy} defaultProps={{kind:'skills'}} durationInFrames={180} fps={30} width={1200} height={704}/>
      <Composition id="Contact" component={SectionStudy} defaultProps={{kind:'contact'}} durationInFrames={180} fps={30} width={1200} height={704}/>
    </>
  );
};
