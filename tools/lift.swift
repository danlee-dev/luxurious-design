import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: lift <in> <out>"); exit(1) }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
guard let src = CGImageSourceCreateWithURL(inURL as CFURL, nil),
      let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else { print("cannot read"); exit(1) }
let req = VNGenerateForegroundInstanceMaskRequest()
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
  try handler.perform([req])
  guard let result = req.results?.first else { print("no subject"); exit(2) }
  let buf = try result.generateMaskedImage(ofInstances: result.allInstances, from: handler, croppedToInstancesExtent: false)
  let ci = CIImage(cvPixelBuffer: buf)
  let ctx = CIContext()
  guard let outCG = ctx.createCGImage(ci, from: ci.extent) else { print("render fail"); exit(3) }
  guard let dest = CGImageDestinationCreateWithURL(outURL as CFURL, UTType.png.identifier as CFString, 1, nil) else { exit(4) }
  CGImageDestinationAddImage(dest, outCG, nil)
  CGImageDestinationFinalize(dest)
  print("ok", outCG.width, outCG.height, "instances", result.allInstances.count)
} catch { print("error", error); exit(5) }
