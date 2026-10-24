import SwiftUI

/// Kart's design tokens (spec §3.2). Light mode only: stores are brightly lit.
enum Theme {
    // Surfaces and ink
    static let canvas = Color(hex: 0xF7F3EC)
    static let surface = Color(hex: 0xFFFFFF)
    static let hairline = Color(hex: 0xE6E0D6)
    static let ink = Color(hex: 0x1E2422)
    static let inkSecondary = Color(hex: 0x5E6762)

    // Brand (Kart) and meaning colors
    static let brand = Color(hex: 0x12A189)
    static let brandDeep = Color(hex: 0x0B5E50)
    static let brandSoft = Color(hex: 0xDDF3EE)
    static let amber = Color(hex: 0xE9A23B)
    static let amberSoft = Color(hex: 0xFCEFD9)
    static let amberInk = Color(hex: 0x7A4B07)
    static let green = Color(hex: 0x2F9E5F)
    static let greenSoft = Color(hex: 0xE3F4E9)
    static let greenInk = Color(hex: 0x1C5E38)

    // Type: SF Pro Rounded, nothing under 17 pt
    static let display = Font.system(size: 44, weight: .semibold, design: .rounded)
    static let title = Font.system(size: 28, weight: .semibold, design: .rounded)
    static let headline = Font.system(size: 22, weight: .semibold, design: .rounded)
    static let body = Font.system(size: 20, weight: .regular, design: .rounded)
    static let caption = Font.system(size: 17, weight: .regular, design: .rounded)
    static let speech = Font.system(size: 22, weight: .medium, design: .rounded)

    // Layout
    static let xs: CGFloat = 4, s: CGFloat = 8, m: CGFloat = 12, l: CGFloat = 16, xl: CGFloat = 24, xxl: CGFloat = 32, xxxl: CGFloat = 48
    static let cardRadius: CGFloat = 24
    static let tileRadius: CGFloat = 16
    static let minTap: CGFloat = 64

    // Motion
    static let spring = Animation.spring(response: 0.45, dampingFraction: 0.82)
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// The screen's one primary button: brand fill, white text, 64 pt tall.
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.headline)
            .foregroundStyle(.white)
            .padding(.horizontal, Theme.xl)
            .frame(minHeight: Theme.minTap)
            .background(Theme.brand.opacity(configuration.isPressed ? 0.85 : 1), in: RoundedRectangle(cornerRadius: 18))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.spring, value: configuration.isPressed)
    }
}

/// Outlined secondary button.
struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.headline)
            .foregroundStyle(Theme.ink)
            .padding(.horizontal, Theme.xl)
            .frame(minHeight: Theme.minTap)
            .background(Theme.surface.opacity(configuration.isPressed ? 0.7 : 1), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Theme.hairline, lineWidth: 1.5))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.spring, value: configuration.isPressed)
    }
}
