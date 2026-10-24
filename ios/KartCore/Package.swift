// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "KartCore",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "KartCore", targets: ["KartCore"]),
        .library(name: "KartSupabase", targets: ["KartSupabase"]),
    ],
    targets: [
        .target(name: "KartCore"),
        .target(name: "KartSupabase", dependencies: ["KartCore"]),
        .testTarget(name: "KartCoreTests", dependencies: ["KartCore"]),
        .testTarget(name: "KartSupabaseTests", dependencies: ["KartSupabase", "KartCore"]),
    ]
)
