// Print the face boxes macOS Vision finds in each image, largest first.
//
//   swiftc -O tools/faces.swift -o tools/faces
//   tools/faces a_cut.png b_cut.png c_cut.png > faces.txt
//
// Each line reads "<file> face x=<left> y=<top> w=<width> h=<height> img=<W>x<H>"
// in pixels of that image, origin at the top left. tools/portrait_align.py reads
// these lines. Images without a face are reported on stderr.
import Foundation
import Vision
import ImageIO

func warn(_ message: String) {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
}

let paths = Array(CommandLine.arguments.dropFirst())
if paths.isEmpty {
  print("usage: faces <image> [<image> ...]")
  exit(1)
}

var failed = false
for path in paths {
  let name = (path as NSString).lastPathComponent
  let url = URL(fileURLWithPath: path)
  guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
        let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
    warn("\(name) unreadable")
    failed = true
    continue
  }
  let req = VNDetectFaceRectanglesRequest()
  let handler = VNImageRequestHandler(cgImage: cg, options: [:])
  do {
    try handler.perform([req])
  } catch {
    warn("\(name) error \(error)")
    failed = true
    continue
  }
  let W = Double(cg.width), H = Double(cg.height)
  let faces = (req.results ?? []).sorted { $0.boundingBox.width > $1.boundingBox.width }
  if faces.isEmpty { warn("\(name) no face") }
  for f in faces {
    let b = f.boundingBox  // normalized, origin at the bottom left
    let x = b.origin.x * W, w = b.size.width * W, h = b.size.height * H
    let top = (1 - b.origin.y - b.size.height) * H
    print(String(format: "%@ face x=%.0f y=%.0f w=%.0f h=%.0f img=%.0fx%.0f", name, x, top, w, h, W, H))
  }
}
exit(failed ? 2 : 0)
