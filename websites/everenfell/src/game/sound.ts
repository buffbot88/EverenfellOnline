/** Original UI sounds, played server-authoritatively nowhere: pure presentation.
 *
 * Files are genuine Flash-client MP3s vendored under
 * websites/everenfell/assets/sounds/ (dev-only until rights confirmed;
 * never copied to dist). Served exactly like map tiles: `/assets/` in
 * dev, authenticated `/protected-assets/` in prod. WebAudio with one
 * master gain; mute persists in localStorage. The context resumes on
 * the first pointer gesture to satisfy autoplay policy.
 */
const MUTE_KEY = 'evf-muted';

function soundUrl(file: string): string {
  return `${import.meta.env.DEV ? '/assets/' : '/protected-assets/' }sounds/${file}`;
}

class SoundService {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private muted = false;
  private listeners = new Set<(muted: boolean) => void>();

  constructor() {
    try {
      this.muted = window.localStorage.getItem(MUTE_KEY) === '1';
    } catch {
      this.muted = false;
    }
  }

  get isMuted(): boolean {
    return this.muted;
  }

  onMuteChange(listener: (muted: boolean) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    try {
      window.localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
    } catch {
      // Private mode: mute still applies to this session.
    }
    if (this.master && this.context) {
      this.master.gain.setValueAtTime(muted ? 0 : 1, this.context.currentTime);
    }
    this.listeners.forEach((listener) => listener(muted));
  }

  /** Resume the context from a user gesture; safe to call repeatedly. */
  unlock(): void {
    const context = this.ensureContext();
    if (context && context.state === 'suspended') {
      void context.resume();
    }
  }

  /** Fire-and-forget UI click. Never rejects into click handlers. */
  click(): void {
    void this.play('clickBtn.mp3');
  }

  /** Fire-and-forget close/back sound. */
  close(): void {
    void this.play('closeP.mp3');
  }

  /** Fire-and-forget tab/class-switch sound. */
  tab(): void {
    void this.play('tab_change.mp3');
  }

  /** Fire-and-forget panel open/close sounds. */
  panel(opened: boolean): void {
    void this.play(opened ? 'panelOpen.mp3' : 'panelClose.mp3');
  }

  async play(file: string): Promise<void> {
    if (this.muted) return;
    const context = this.ensureContext();
    if (!context || !this.master) return;
    if (context.state === 'suspended') {
      try {
        await context.resume();
      } catch {
        return;
      }
    }
    let buffer = this.buffers.get(file);
    if (!buffer) {
      try {
        const res = await fetch(soundUrl(file), { cache: 'force-cache' });
        if (!res.ok) return;
        buffer = await context.decodeAudioData(await res.arrayBuffer());
        this.buffers.set(file, buffer);
      } catch {
        return;
      }
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.master);
    source.start();
  }

  private ensureContext(): AudioContext | null {
    if (this.context && this.master) return this.context;
    try {
      const Context =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!Context) return null;
      this.context = new Context();
      this.master = this.context.createGain();
      this.master.gain.value = this.muted ? 0 : 1;
      this.master.connect(this.context.destination);
      return this.context;
    } catch {
      return null;
    }
  }
}

export const sound = new SoundService();
