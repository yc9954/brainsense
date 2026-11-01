import AVFoundation
import CoreVideo

/// Keeps the last `Config.clipSeconds` of frames from the glasses stream and encodes them to MP4 on demand.
final class ClipRecorder {
    private var frames: [(CVPixelBuffer, CMTime)] = []
    private let lock = NSLock()
    private let fps: Double

    init(fps: Double = 15) { self.fps = fps }

    func push(_ pixelBuffer: CVPixelBuffer, at time: CMTime) {
        lock.lock(); defer { lock.unlock() }
        frames.append((pixelBuffer, time))
        let maxFrames = Int(Config.clipSeconds * fps)
        if frames.count > maxFrames { frames.removeFirst(frames.count - maxFrames) }
    }

    /// Encode the ring buffer to an H.264 MP4 (silent audio track added server-side is not needed; TRIBE tolerates no audio).
    func exportClip() async throws -> URL {
        lock.lock(); let snapshot = frames; lock.unlock()
        guard let first = snapshot.first else { throw NSError(domain: "ClipRecorder", code: 1, userInfo: [NSLocalizedDescriptionKey: "no frames buffered"]) }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("clip-\(UUID().uuidString).mp4")
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
        let w = CVPixelBufferGetWidth(first.0), h = CVPixelBufferGetHeight(first.0)
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: w, AVVideoHeightKey: h])
        input.expectsMediaDataInRealTime = false
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
        writer.add(input)
        writer.startWriting(); writer.startSession(atSourceTime: .zero)
        let frameDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
        var t = CMTime.zero
        for (buf, _) in snapshot {
            while !input.isReadyForMoreMediaData { try await Task.sleep(nanoseconds: 2_000_000) }
            adaptor.append(buf, withPresentationTime: t)
            t = CMTimeAdd(t, frameDuration)
        }
        input.markAsFinished()
        await writer.finishWriting()
        return url
    }
}
