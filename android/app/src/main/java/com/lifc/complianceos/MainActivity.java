package com.lifc.complianceos;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * LIFC Compliance OS – Android client.
 * A secure WebView shell for the Compliance OS server: login, testing, evidence upload
 * (files or camera), downloads, and printing / saving reports as PDF.
 */
public class MainActivity extends Activity {

    private static final int REQ_FILE = 1001;
    private static final String PREFS = "cct";
    private static final String SETUP_PAGE = "file:///android_asset/setup.html";
    private static final String OFFLINE_PAGE = "file:///android_asset/offline.html";

    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;
    private String serverUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " LIFCComplianceOS/1.0");

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, false);

        web.addJavascriptInterface(new Bridge(), "AndroidBridge");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (isOwnUrl(u)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) view.loadUrl(OFFLINE_PAGE);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                return openChooser(callback, params);
            }
        });

        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) ->
                startDownload(url, userAgent, contentDisposition, mimeType));

        serverUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString("server", null);
        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else if (serverUrl == null) {
            web.loadUrl(SETUP_PAGE);
        } else {
            web.loadUrl(serverUrl);
        }
    }

    private boolean isOwnUrl(Uri u) {
        if (u == null) return false;
        if ("file".equals(u.getScheme()) && u.getPath() != null && u.getPath().startsWith("/android_asset/")) return true;
        if (serverUrl == null) return false;
        Uri s = Uri.parse(serverUrl);
        return s.getScheme() != null && s.getScheme().equals(u.getScheme())
                && s.getHost() != null && s.getHost().equalsIgnoreCase(u.getHost())
                && s.getPort() == u.getPort();
    }

    // ------------------------------------------------------------------ evidence upload
    private boolean openChooser(ValueCallback<Uri[]> callback, WebChromeClient.FileChooserParams params) {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        fileCallback = callback;
        cameraUri = null;
        Intent intent;
        boolean wantsCamera = params.isCaptureEnabled() && acceptsImages(params) && Build.VERSION.SDK_INT >= 29;
        if (wantsCamera) {
            cameraUri = createImageUri();
        }
        if (cameraUri != null) {
            intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } else {
            intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("*/*");
            if (params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            }
            intent = Intent.createChooser(intent, "Attach evidence");
        }
        try {
            startActivityForResult(intent, REQ_FILE);
            return true;
        } catch (Exception e) {
            fileCallback = null;
            toast("No app available to pick a file");
            return false;
        }
    }

    private boolean acceptsImages(WebChromeClient.FileChooserParams params) {
        String[] types = params.getAcceptTypes();
        if (types == null) return true;
        for (String t : types) {
            if (t == null || t.isEmpty() || t.startsWith("image/")) return true;
        }
        return false;
    }

    private Uri createImageUri() {
        try {
            ContentValues v = new ContentValues();
            v.put(MediaStore.Images.Media.DISPLAY_NAME, "LIFC_evidence_" + System.currentTimeMillis() + ".jpg");
            v.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
            v.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/LIFC Compliance");
            return getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
        } catch (Exception e) {
            return null;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_FILE || fileCallback == null) return;
        Uri[] result = null;
        if (resultCode == RESULT_OK) {
            if (cameraUri != null) {
                result = new Uri[]{cameraUri};
            } else if (data != null) {
                ClipData clip = data.getClipData();
                if (clip != null) {
                    result = new Uri[clip.getItemCount()];
                    for (int i = 0; i < clip.getItemCount(); i++) result[i] = clip.getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                }
            }
        } else if (cameraUri != null) {
            try { getContentResolver().delete(cameraUri, null, null); } catch (Exception ignored) { }
        }
        fileCallback.onReceiveValue(result);
        fileCallback = null;
        cameraUri = null;
    }

    // ------------------------------------------------------------------ downloads & files
    private void startDownload(String url, String userAgent, String contentDisposition, String mimeType) {
        if (url.startsWith("blob:") || url.startsWith("data:")) {
            toast("Use the app's export buttons to save this file");
            return;
        }
        try {
            String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            String cookies = CookieManager.getInstance().getCookie(url);
            if (cookies != null) r.addRequestHeader("Cookie", cookies);
            r.addRequestHeader("User-Agent", userAgent);
            r.addRequestHeader("X-CCT", "1");
            r.setTitle(name);
            r.setMimeType(mimeType);
            r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "LIFC Compliance/" + name);
            DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            dm.enqueue(r);
            toast("Downloading " + name);
        } catch (Exception e) {
            toast("Download failed: " + e.getMessage());
        }
    }

    private void saveBytes(String name, byte[] data, String mime) {
        String safe = name.replaceAll("[\\\\/:*?\"<>|]", "_");
        try {
            Uri uri;
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, safe);
                v.put(MediaStore.Downloads.MIME_TYPE, mime);
                v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/LIFC Compliance");
                uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new Exception("storage unavailable");
                try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                    if (os == null) throw new Exception("storage unavailable");
                    os.write(data);
                }
                toast("Saved to Downloads/LIFC Compliance/" + safe);
            } else {
                File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                File f = new File(dir, safe);
                try (FileOutputStream os = new FileOutputStream(f)) {
                    os.write(data);
                }
                toast("Saved to " + f.getAbsolutePath());
                return;
            }
            try {
                Intent view = new Intent(Intent.ACTION_VIEW);
                view.setDataAndType(uri, mime);
                view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                startActivity(Intent.createChooser(view, "Open " + safe));
            } catch (Exception ignored) { }
        } catch (Exception e) {
            toast("Could not save file: " + e.getMessage());
        }
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    // ------------------------------------------------------------------ JavaScript bridge
    private class Bridge {
        @JavascriptInterface
        public String version() {
            return "1.0.0";
        }

        @JavascriptInterface
        public String getServer() {
            return serverUrl == null ? "" : serverUrl;
        }

        @JavascriptInterface
        public void setServer(final String url) {
            runOnUiThread(() -> {
                String u = url == null ? "" : url.trim();
                if (u.isEmpty()) return;
                if (!u.startsWith("http://") && !u.startsWith("https://")) u = "https://" + u;
                while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
                u = u + "/";
                serverUrl = u;
                SharedPreferences.Editor e = getSharedPreferences(PREFS, MODE_PRIVATE).edit();
                e.putString("server", u).apply();
                web.clearHistory();
                web.loadUrl(u);
            });
        }

        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(() -> web.loadUrl(SETUP_PAGE));
        }

        @JavascriptInterface
        public void retry() {
            runOnUiThread(() -> web.loadUrl(serverUrl != null ? serverUrl : SETUP_PAGE));
        }

        @JavascriptInterface
        public void saveFile(final String name, final String base64, final String mime) {
            final byte[] data = Base64.decode(base64, Base64.DEFAULT);
            runOnUiThread(() -> saveBytes(name, data, mime == null || mime.isEmpty() ? "application/octet-stream" : mime));
        }

        @JavascriptInterface
        public void printPage(final String title) {
            runOnUiThread(() -> {
                PrintManager pm = (PrintManager) getSystemService(PRINT_SERVICE);
                PrintDocumentAdapter adapter = web.createPrintDocumentAdapter(title);
                PrintAttributes attrs = new PrintAttributes.Builder()
                        .setMediaSize(PrintAttributes.MediaSize.ISO_A4)
                        .build();
                pm.print(title, adapter, attrs);
            });
        }
    }

    // ------------------------------------------------------------------ lifecycle
    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (web != null) web.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }
}
