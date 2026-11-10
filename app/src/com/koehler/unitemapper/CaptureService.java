package com.koehler.unitemapper;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.IBinder;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Tap-to-capture overlay.
 *
 * Draws a nearly transparent window on top of the game and records where you tap,
 * so the coordinate for each control comes from your finger instead of a guess.
 * The game keeps running underneath; taps are swallowed by the overlay.
 */
public class CaptureService extends Service {

    /** app profile keys, in the order they are captured */
    private static final String[] KEYS = {
            "a", "x", "b", "y", "lb", "lt", "recall", "move", "camera"
    };
    private static final String[] LABELS = {
            "Basic attack",
            "Move 1",
            "Move 2",
            "Battle item",
            "Score",
            "Unite Move",
            "Recall / teleport to base",
            "Movement stick CENTRE",
            "Camera area",
    };

    private WindowManager wm;
    private FrameLayout overlay;
    private TextView hint;
    private int idx = 0;
    private final Map<String, int[]> recorded = new LinkedHashMap<>();

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onCreate() {
        super.onCreate();
        wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        recorded.clear();
        idx = 0;
        showOverlay();
        return START_NOT_STICKY;
    }

    private void showOverlay() {
        overlay = new FrameLayout(this);
        overlay.setBackgroundColor(0x14000000);      // barely dim: game stays readable

        hint = new TextView(this);
        hint.setTextColor(Color.WHITE);
        hint.setTextSize(20);
        hint.setGravity(Gravity.CENTER);
        hint.setBackgroundColor(0xCC000000);
        hint.setPadding(24, 24, 24, 24);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.TOP;
        lp.topMargin = 80;
        hint.setLayoutParams(lp);
        updateHint();

        overlay.addView(hint);
        overlay.setOnTouchListener((v, e) -> {
            if (e.getAction() == MotionEvent.ACTION_UP) {
                record(e.getRawX(), e.getRawY());
            }
            return true;      // swallow everything: the game must not react
        });

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                        : WindowManager.LayoutParams.TYPE_PHONE,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        try {
            wm.addView(overlay, params);
        } catch (Exception e) {
            Toast.makeText(this, "overlay blocked: " + e.getMessage(), Toast.LENGTH_LONG).show();
            stopSelf();
        }
    }

    private void updateHint() {
        String what = LABELS[idx];
        hint.setText("Tap " + (idx + 1) + "/" + KEYS.length + ": " + what
                + "\n\ntap the BOTTOM-LEFT corner to cancel");
    }

    private void record(float x, float y) {
        if (x < 200 && y > 1200) {          // cancel zone: bottom-left corner
            finishCapture(false);
            return;
        }
        recorded.put(KEYS[idx], new int[]{(int) x, (int) y});
        idx++;
        if (idx >= KEYS.length) {
            finishCapture(true);
        } else {
            updateHint();
        }
    }

    private void finishCapture(boolean save) {
        if (overlay != null) {
            try { wm.removeView(overlay); } catch (Exception ignored) { }
            overlay = null;
        }
        if (save) {
            try {
                File f = profileFile();
                String existing = f.exists()
                        ? new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8)
                        : "{\n}\n";
                StringBuilder sb = new StringBuilder(existing.trim());
                if (sb.length() == 0) sb.append("{}");
                int close = sb.lastIndexOf("}");
                sb.deleteCharAt(close);
                boolean first = sb.toString().trim().endsWith("{");
                for (Map.Entry<String, int[]> e : recorded.entrySet()) {
                    if (!first) sb.append(",");
                    sb.append("\n  \"").append(e.getKey()).append("_x\": ").append(e.getValue()[0])
                      .append(",\n  \"").append(e.getKey()).append("_y\": ").append(e.getValue()[1]);
                    first = false;
                }
                sb.append("\n}\n");
                boolean ok = false;
                for (int attempt = 0; attempt < 2 && !ok; attempt++) {
                    try (FileOutputStream out = new FileOutputStream(f)) {
                        out.write(sb.toString().getBytes(StandardCharsets.UTF_8));
                        ok = true;
                    } catch (Exception e) {
                        f.delete();     // foreign-owned (adb-pushed) file: drop and retry
                    }
                }
                Toast.makeText(this, ok
                        ? "Captured " + recorded.size() + " controls"
                        : "save failed — check storage permissions", Toast.LENGTH_LONG).show();
            } catch (Exception e) {
                Toast.makeText(this, "save failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        } else {
            Toast.makeText(this, "capture cancelled", Toast.LENGTH_SHORT).show();
        }
        stopSelf();
    }

    private File profileFile() {
        File dir = getExternalFilesDir(null);
        if (dir == null) dir = getFilesDir();
        return new File(dir, "unite_profile.json");
    }
}
