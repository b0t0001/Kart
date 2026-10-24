import Foundation
import Testing
@testable import KartCore

private func defaults() -> UserDefaults {
    let name = "kart-tests-\(UUID().uuidString)"
    let d = UserDefaults(suiteName: name)!
    d.removePersistentDomain(forName: name)
    return d
}

@Test func liveBackendIsTheDefaultWhenConfigured() {
    #expect(LaunchPreferences.backend(defaults: defaults(), scenario: nil, hasConfig: true) == .supabase)
    #expect(LaunchPreferences.backend(defaults: defaults(), scenario: nil, hasConfig: false) == .mock)
}

@Test func scenariosAlwaysUseTheMock() {
    #expect(LaunchPreferences.backend(defaults: defaults(), scenario: "shopping", hasConfig: true) == .mock)
}

@Test func theOfflineSwitchSurvivesARelaunch() {
    let d = defaults()
    LaunchPreferences.persist(.mock, defaults: d)                // debug panel: "Use offline demo mode"
    #expect(LaunchPreferences.backend(defaults: d, scenario: nil, hasConfig: true) == .mock)
    LaunchPreferences.persist(.supabase, defaults: d)
    #expect(LaunchPreferences.backend(defaults: d, scenario: nil, hasConfig: true) == .supabase)
    #expect(LaunchPreferences.backend(defaults: d, scenario: nil, hasConfig: false) == .mock)   // no config: can't go live
}

@Test func theScriptedVoiceIsTheDefault() {
    #expect(LaunchPreferences.voice(defaults: defaults(), scenario: nil, hasConfig: true) == .mock)
}

@Test func theRealVoiceSwitchSurvivesARelaunch() {
    let d = defaults()
    LaunchPreferences.persistVoice(.line, defaults: d)                // debug panel: "Use real voice"
    #expect(LaunchPreferences.voice(defaults: d, scenario: nil, hasConfig: true) == .line)
    #expect(LaunchPreferences.voice(defaults: d, scenario: nil, hasConfig: false) == .mock)   // no backend: no voice token
    #expect(LaunchPreferences.voice(defaults: d, scenario: "shopping", hasConfig: true) == .mock)   // screenshots stay scripted
    LaunchPreferences.persistVoice(.mock, defaults: d)
    #expect(LaunchPreferences.voice(defaults: d, scenario: nil, hasConfig: true) == .mock)
}

@Test func holdToTalkIsOffByDefaultAndSticks() {
    let d = defaults()
    #expect(LaunchPreferences.holdToTalk(defaults: d) == false)        // hands-free by default
    LaunchPreferences.persistHoldToTalk(true, defaults: d)             // debug panel: "Hold to talk"
    #expect(LaunchPreferences.holdToTalk(defaults: d) == true)
}
