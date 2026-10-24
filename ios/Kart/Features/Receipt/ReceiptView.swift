import KartCore
import SwiftUI

/// The end of the trip: what you saved and how long it took. Returns to Welcome on its own after 30 s.
struct ReceiptView: View {
    let model: AppModel
    @State private var celebrate: ReactionEvent?

    var body: some View {
        let receipt = model.backend.receipt
        VStack(spacing: Theme.xl) {
            AvatarView(mood: .idle, reaction: celebrate, size: 240)
            Text("You're all set").font(Theme.title).foregroundStyle(Theme.ink)
            if let receipt {
                Text(TripFormat.receiptHeadline(savings: receipt.savings, durationS: receipt.durationS))
                    .font(Theme.headline).foregroundStyle(receipt.savings > 0 ? Theme.greenInk : Theme.ink)
                Text("\(receipt.itemCount) \(receipt.itemCount == 1 ? "item" : "items") · \(Money.format(receipt.total))")
                    .font(Theme.body).foregroundStyle(Theme.inkSecondary)
            }
            Button {
                Task { await model.finishTrip() }
            } label: {
                Text("Done").frame(minWidth: 220)
            }
            .buttonStyle(PrimaryButtonStyle())
            .padding(.top, Theme.l)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { celebrate = ReactionEvent(reaction: .celebrate) }
        .task {
            try? await Task.sleep(for: .seconds(30))
            if !Task.isCancelled { await model.finishTrip() }
        }
    }
}
