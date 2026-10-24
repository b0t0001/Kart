import SwiftUI
import UIKit

/// A rounded category tile; the camera's photo replaces the symbol when there is one.
struct ProductTile: View {
    let category: String?
    var size: CGFloat = 44
    var snapshotURL: URL? = nil

    var body: some View {
        let style = Self.style(for: category)
        RoundedRectangle(cornerRadius: size * 0.3)
            .fill(style.color.opacity(0.16))
            .frame(width: size, height: size)
            .overlay {
                if let snapshotURL {
                    AsyncImage(url: snapshotURL) { image in
                        image.resizable().scaledToFill()
                    } placeholder: {
                        symbol(style)
                    }
                    .clipShape(RoundedRectangle(cornerRadius: size * 0.3))
                } else {
                    symbol(style)
                }
            }
    }

    private func symbol(_ style: (symbol: String, color: Color)) -> some View {
        Image(systemName: style.symbol)
            .font(.system(size: size * 0.46, weight: .semibold))
            .foregroundStyle(style.color)
    }

    static func style(for category: String?) -> (symbol: String, color: Color) {
        let (symbol, color): (String, Color) = switch category {
        case "produce": ("carrot", Theme.green)
        case "bakery": ("birthday.cake", Color(hex: 0xC27A2C))
        case "meat": ("frying.pan", Color(hex: 0xC2453B))
        case "cheese": ("chart.pie", Theme.amber)
        case "dairy": ("cup.and.saucer", Color(hex: 0x3A7BC8))
        case "pasta": ("fork.knife", Color(hex: 0xB8862B))
        case "sauce": ("drop", Color(hex: 0xC2453B))
        case "salsa": ("flame", Color(hex: 0xD9622B))
        case "snacks": ("popcorn", Color(hex: 0xD9A21B))
        case "spices": ("leaf", Theme.green)
        case "household": ("house", Color(hex: 0x6B6FA8))
        default: ("bag", Theme.inkSecondary)
        }
        return (UIImage(systemName: symbol) == nil ? "bag" : symbol, color)
    }
}
