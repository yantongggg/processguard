import {Composition, registerRoot} from 'remotion';
import {ProcessGuardDemo} from './ProcessGuardDemo';
import {ProcessGuardMovie} from './ProcessGuardMovie';
import './styles.css';
import './movie.css';

const fps = 24;
const durationInFrames = fps * 300 - 12;

const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="ProcessGuardDemo"
        component={ProcessGuardDemo}
        durationInFrames={durationInFrames}
        fps={fps}
        width={1920}
        height={1080}
      />
      <Composition
        id="ProcessGuardMovie"
        component={ProcessGuardMovie}
        durationInFrames={durationInFrames}
        fps={fps}
        width={1920}
        height={1080}
      />
    </>
  );
};

registerRoot(RemotionRoot);