// nova_aec — echo-cancelled mic + speaker for the hub (macOS voice processing, same as FaceTime).
// Plays WAVs and records the mic through ONE AVAudioEngine with voice processing on, so the mic
// stream has Nova's own voice subtracted out ("Nova, stop" stays audible while it talks).
//
//   stdout : mic audio, 16 kHz mono int16 LE, continuous
//   stdin  : "play <wav path>" | "stop" | "quit"   (one per line)
//   stderr : "ready vp=1" | "done <path>" | "err <msg>"
// Build (on the M4 for the Intel hub):
//   swiftc -O -target x86_64-apple-macos12 nova_aec.swift -o nova_aec
// Flag: --no-vp disables voice processing (A/B test).
import AVFoundation
import Foundation

setvbuf(stderr, nil, _IONBF, 0)
func log(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

let useVP = !CommandLine.arguments.contains("--no-vp")
let engine = AVAudioEngine()
_ = engine.outputNode; _ = engine.mainMixerNode   // touch output BEFORE enabling VP, else start() fails -10875 (Monterey)
let input = engine.inputNode
let player = AVAudioPlayerNode()
var vpOn = false
if useVP {
    do { try input.setVoiceProcessingEnabled(true); vpOn = true } catch { log("err vp: \(error)") }
}
engine.attach(player)
var playFormat = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!  // Kokoro's format
engine.connect(player, to: engine.mainMixerNode, format: playFormat)

let outFmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
let inFmt = input.outputFormat(forBus: 0)                 // VP gives 3 ch here; ch 0 is the cleaned voice
let monoFmt = AVAudioFormat(standardFormatWithSampleRate: inFmt.sampleRate, channels: 1)!
let conv = AVAudioConverter(from: monoFmt, to: outFmt)!
let stdout = FileHandle.standardOutput
input.installTap(onBus: 0, bufferSize: 1024, format: inFmt) { buf, _ in
    guard let mono = AVAudioPCMBuffer(pcmFormat: monoFmt, frameCapacity: buf.frameLength),
          let src = buf.floatChannelData, let dst = mono.floatChannelData else { return }
    mono.frameLength = buf.frameLength
    dst[0].update(from: src[0], count: Int(buf.frameLength))
    let cap = AVAudioFrameCount(Double(buf.frameLength) * 16000 / inFmt.sampleRate) + 16
    guard let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
    var fed = false
    conv.convert(to: out, error: nil) { _, status in
        if fed { status.pointee = .noDataNow; return nil }
        fed = true; status.pointee = .haveData; return mono
    }
    let n = Int(out.frameLength)
    if n > 0, let p = out.int16ChannelData { stdout.write(Data(bytes: p[0], count: n * 2)) }
}

func start() {
    do { try engine.start(); player.play() } catch { log("err start: \(error)") }
}
start()
// device unplugged/replugged -> engine stops; bring it back
NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: nil) { _ in
    log("err config change, restarting"); start()
}
log("ready vp=\(vpOn ? 1 : 0) in=\(Int(inFmt.sampleRate))Hz/\(inFmt.channelCount)ch")

DispatchQueue.global().async {
    while let line = readLine() {
        if line == "quit" { exit(0) }
        if line == "stop" { player.stop(); player.play(); continue }
        guard line.hasPrefix("play ") else { continue }
        let path = String(line.dropFirst(5))
        do {
            let f = try AVAudioFile(forReading: URL(fileURLWithPath: path))
            if f.processingFormat != playFormat {          // e.g. a non-Kokoro WAV
                playFormat = f.processingFormat
                engine.disconnectNodeOutput(player)
                engine.connect(player, to: engine.mainMixerNode, format: playFormat)
            }
            player.scheduleFile(f, at: nil, completionCallbackType: .dataPlayedBack) { _ in log("done \(path)") }
            if !player.isPlaying { player.play() }
        } catch { log("err play \(path): \(error)"); log("done \(path)") }
    }
    exit(0)
}
RunLoop.main.run()
