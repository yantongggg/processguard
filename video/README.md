# ProcessGuard Demo Video

Remotion source for a 5:00 ProcessGuard demo video matching the hackathon structure:

- 0:00-0:30 Problem
- 0:30-1:15 Solution
- 1:15-2:15 Live compliant demo
- 2:15-3:15 Violation demo: `skip_2fa_for_vip`
- 3:15-4:00 Gray-zone demo with LLM judge fields
- 4:00-4:40 Architecture
- 4:40-5:00 Human role

## Commands

```bash
cd video
npm install
npm run preview
npm run render
```

The production MP4 renders to:

```text
video/out/processguard-demo.mp4
```

For a quick draft render while editing:

```bash
npm run render:fast
```

Upload the final MP4 to YouTube, Vimeo, or Youku. The video is designed to stand on its own with on-screen narration captions, so it can be uploaded with or without an added voiceover track.