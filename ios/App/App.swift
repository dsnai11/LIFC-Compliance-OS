import UIKit
import WebKit

// LIFC Compliance OS – iOS WebView shell (mirrors the Android MainActivity).
// Reuses the web client's AndroidBridge hooks via a polyfill, so index.html needs no changes.

let kServerKey = "serverURL"

final class VC: UIViewController, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    var web: WKWebView!
    var dlDest: URL?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.98, green: 0.97, blue: 0.97, alpha: 1)
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()                       // persistent cookies (session survives relaunch)
        cfg.allowsInlineMediaPlayback = true
        let ucc = WKUserContentController()
        let js = """
        window.AndroidBridge={
          saveFile:function(n,b64,t){window.webkit.messageHandlers.save.postMessage({name:n,data:b64,type:t});},
          printPage:function(n){window.webkit.messageHandlers.print.postMessage(n||'Report');},
          changeServer:function(){window.webkit.messageHandlers.server.postMessage('');}
        };
        """
        ucc.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        for n in ["save", "print", "server"] { ucc.add(self, name: n) }
        cfg.userContentController = ucc
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        let g = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([web.topAnchor.constraint(equalTo: g.topAnchor), web.bottomAnchor.constraint(equalTo: view.bottomAnchor),
                                     web.leadingAnchor.constraint(equalTo: g.leadingAnchor), web.trailingAnchor.constraint(equalTo: g.trailingAnchor)])
        let lp = UILongPressGestureRecognizer(target: self, action: #selector(askServer))   // two-finger long-press = change server
        lp.numberOfTouchesRequired = 2; lp.minimumPressDuration = 1.2
        view.addGestureRecognizer(lp)
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if let s = UserDefaults.standard.string(forKey: kServerKey), let u = URL(string: s) { web.load(URLRequest(url: u)) }
        else { askServer() }
    }

    @objc func askServer() {
        guard presentedViewController == nil else { return }
        let a = UIAlertController(title: "Server address", message: "Address of your Compliance OS server, e.g. https://compliance.lifc.in", preferredStyle: .alert)
        a.addTextField { t in
            t.placeholder = "https://compliance.lifc.in"; t.keyboardType = .URL; t.autocapitalizationType = .none; t.autocorrectionType = .no
            t.text = UserDefaults.standard.string(forKey: kServerKey)
        }
        a.addAction(UIAlertAction(title: "Connect", style: .default) { _ in
            var v = (a.textFields?.first?.text ?? "").trimmingCharacters(in: .whitespaces)
            if v.isEmpty { self.askServer(); return }
            if !v.contains("://") { v = "https://" + v }
            UserDefaults.standard.set(v, forKey: kServerKey)
            if let u = URL(string: v) { self.web.load(URLRequest(url: u)) }
        })
        if UserDefaults.standard.string(forKey: kServerKey) != nil { a.addAction(UIAlertAction(title: "Cancel", style: .cancel)) }
        present(a, animated: true)
    }

    // MARK: bridge
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        switch m.name {
        case "server": askServer()
        case "print":
            let pi = UIPrintInfo(dictionary: nil); pi.outputType = .general; pi.jobName = (m.body as? String) ?? "Report"
            let pc = UIPrintInteractionController.shared
            pc.printInfo = pi; pc.printFormatter = web.viewPrintFormatter(); pc.present(animated: true)
        case "save":
            guard let d = m.body as? [String: Any], let name = d["name"] as? String, let b64 = d["data"] as? String, let data = Data(base64Encoded: b64) else { return }
            let safe = name.replacingOccurrences(of: "/", with: "_")
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(safe)
            try? data.write(to: url); share(url)
        default: break
        }
    }

    func share(_ url: URL) {
        let s = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        s.popoverPresentationController?.sourceView = view
        s.popoverPresentationController?.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.midY, width: 1, height: 1)
        present(s, animated: true)
    }

    // MARK: navigation / downloads
    func webView(_ w: WKWebView, decidePolicyFor r: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disp = ((r.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? "").lowercased()
        decisionHandler(disp.hasPrefix("attachment") || !r.canShowMIMEType ? .download : .allow)
    }
    func webView(_ w: WKWebView, navigationResponse: WKNavigationResponse, didBecome d: WKDownload) { d.delegate = self }
    func webView(_ w: WKWebView, navigationAction: WKNavigationAction, didBecome d: WKDownload) { d.delegate = self }
    func download(_ d: WKDownload, decideDestinationUsing r: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        dlDest = dir.appendingPathComponent(suggestedFilename); completionHandler(dlDest)
    }
    func downloadDidFinish(_ d: WKDownload) { if let u = dlDest { share(u) } }
    func download(_ d: WKDownload, didFailWithError e: Error, resumeData: Data?) { notice("Download failed: \(e.localizedDescription)") }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { failed(e) }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { failed(e) }
    func failed(_ e: Error) {
        if (e as NSError).code == NSURLErrorCancelled || presentedViewController != nil { return }
        let a = UIAlertController(title: "Cannot reach server", message: e.localizedDescription, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Retry", style: .default) { _ in self.web.reload(); if self.web.url == nil, let s = UserDefaults.standard.string(forKey: kServerKey), let u = URL(string: s) { self.web.load(URLRequest(url: u)) } })
        a.addAction(UIAlertAction(title: "Change server", style: .default) { _ in self.askServer() })
        present(a, animated: true)
    }
    func notice(_ m: String) { let a = UIAlertController(title: nil, message: m, preferredStyle: .alert); a.addAction(UIAlertAction(title: "OK", style: .default)); present(a, animated: true) }

    // JS alert/confirm (the client uses alert() for integrity results)
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: m, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() }); present(a, animated: true)
    }
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: m, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) }); present(a, animated: true)
    }
    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt p: String, defaultText: String?, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: p, preferredStyle: .alert); a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(a.textFields?.first?.text) }); present(a, animated: true)
    }
}

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let ws = scene as? UIWindowScene else { return }
        window = UIWindow(windowScene: ws); window?.rootViewController = VC(); window?.makeKeyAndVisible()
    }
}

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(_ a: UIApplication, configurationForConnecting s: UISceneSession, options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let c = UISceneConfiguration(name: "Default", sessionRole: s.role); c.delegateClass = SceneDelegate.self; return c
    }
}
