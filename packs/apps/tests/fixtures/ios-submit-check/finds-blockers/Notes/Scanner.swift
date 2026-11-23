import AVFoundation

/// Turns a photographed paper page into a note.
final class PageScanner {
    func start() -> AVCaptureDevice? {
        return AVCaptureDevice.default(for: .video)
    }
}
