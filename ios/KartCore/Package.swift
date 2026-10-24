// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "KartCore",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [.library(name: "KartCore", targets: ["KartCore"])],
    targets: [
        .target(name: "KartCore"),
        .testTarget(name: "KartCoreTests", dependencies: ["KartCore"]),
    ]
)
