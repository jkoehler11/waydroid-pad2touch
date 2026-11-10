package com.koehler.unitemapper;

import android.app.Activity;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Unite Mapper — enter the on-screen touch coordinates for each control.
 *
 * Writes a JSON profile that the host-side pad2touch daemon reads, then feeds the
 * gamepad into those positions. The mapping engine lives on the host because
 * Android will not hand an app the gamepad while another app (the game) holds focus.
 */
public class MainActivity extends Activity {

    /** action key used by pad2touch.conf -> label shown here */
    private static final String[][] ACTIONS = {
            {"move", "Movement stick centre (radius below)"},
            {"a", "A — basic attack"},
            {"b", "B — Whirlpool / move 2"},
            {"x", "X — Ice Shard / move 1"},
            {"y", "Y — battle item"},
            {"lb", "LB — score"},
            {"lt", "LT — Unite Move"},
            {"camera", "Right stick — camera zone origin"},
            {"recall", "Recall / teleport to base"},
    };

    /** controller buttons offered in the dropdown, "none" disables that action */
    private static final String[] BIND_OPTIONS = {
            "none", "A", "B", "X", "Y", "LB", "RB", "LT", "RT", "START", "BACK"};

    private final Map<String, EditText> xFields = new LinkedHashMap<>();
    private final Map<String, android.widget.Spinner> bindSpinners = new LinkedHashMap<>();
    private final Map<String, EditText> yFields = new LinkedHashMap<>();
    private EditText radiusField;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Unite Mapper — touch coordinates");
        title.setTextSize(20);
        root.addView(title);

        TextView help = new TextView(this);
        help.setText("Screen size " + screenSize() + ".\n"
                + "Enter the pixel position of each control. The host reads this file and "
                + "presses there when you use the matching button.");
        help.setTextSize(12);
        help.setPadding(0, dp(6), 0, dp(12));
        root.addView(help);

        for (String[] action : ACTIONS) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(0, dp(6), 0, dp(6));

            TextView label = new TextView(this);
            label.setText(action[1]);
            label.setTextSize(13);
            label.setWidth(dp(250));
            row.addView(label);

            EditText ex = numberField("X");
            EditText ey = numberField("Y");
            row.addView(ex);
            row.addView(ey);

            xFields.put(action[0], ex);
            yFields.put(action[0], ey);

            // which controller button fires this control
            android.widget.Spinner sp = new android.widget.Spinner(this);
            android.widget.ArrayAdapter<String> ad = new android.widget.ArrayAdapter<>(
                    this, android.R.layout.simple_spinner_item, BIND_OPTIONS);
            ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
            sp.setAdapter(ad);
            sp.setMinimumWidth(dp(150));
            String dflt = defaultBind(action[0]);
            if (dflt != null) {
                sp.setSelection(indexOf(BIND_OPTIONS, dflt));
                bindSpinners.put(action[0], sp);
                row.addView(sp);
            }
            root.addView(row);
        }

        LinearLayout radiusRow = new LinearLayout(this);
        radiusRow.setOrientation(LinearLayout.HORIZONTAL);
        radiusRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView rl = new TextView(this);
        rl.setText("Stick radius (px)");
        rl.setTextSize(13);
        rl.setWidth(dp(250));
        radiusRow.addView(rl);
        radiusField = numberField("r");
        radiusRow.addView(radiusField);
        root.addView(radiusRow);

        Button save = new Button(this);
        save.setText("Save profile");
        save.setOnClickListener(v -> save());
        root.addView(save);

        Button capture = new Button(this);
        capture.setText("Capture coordinates by tapping the game");
        capture.setOnClickListener(v -> startCapture());
        root.addView(capture);

        Button defaults = new Button(this);
        defaults.setText("Load measured defaults (2560x1396)");
        defaults.setOnClickListener(v -> loadDefaults());
        root.addView(defaults);

        TextView path = new TextView(this);
        path.setTextSize(10);
        path.setPadding(0, dp(12), 0, 0);
        path.setText("saved to: " + profileFile().getAbsolutePath());
        root.addView(path);

        setContentView(scroll);
        loadExisting();
    }

    private static String defaultBind(String key) {
        switch (key) {
            case "a":  return "A";      // basic attack
            case "b":  return "RB";     // move 2
            case "x":  return "LB";     // move 1
            case "y":  return "Y";      // battle item
            case "lb": return "X";      // score
            case "lt": return "LT";     // Unite Move
            case "recall": return "BACK"; // teleport to base
            default:   return null;     // movement / camera use the sticks
        }
    }

    private static int indexOf(String[] arr, String v) {
        for (int i = 0; i < arr.length; i++) if (arr[i].equals(v)) return i;
        return 0;
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    private String screenSize() {
        return getResources().getDisplayMetrics().widthPixels + "x"
                + getResources().getDisplayMetrics().heightPixels;
    }

    private EditText numberField(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setInputType(InputType.TYPE_CLASS_NUMBER);
        e.setWidth(dp(90));
        return e;
    }

    private File profileFile() {
        File dir = getExternalFilesDir(null);
        if (dir == null) dir = getFilesDir();
        return new File(dir, "unite_profile.json");
    }

    /** defaults measured off a live UNITE match on a 2560x1396 Waydroid surface */
    private void loadDefaults() {
        int[][] d = {
                {410, 1048},   // move
                {2428, 1228},  // a
                {1996, 1224},  // b
                {2167, 1011},  // x  (ice shard)
                {2164, 1265},  // y  (battle item)
                {1638, 1218},  // lb (score)
                {2370, 828},   // lt (unite)
                {1280, 420},   // camera zone
                {1700, 1300},  // recall / teleport to base
        };
        int i = 0;
        for (String[] action : ACTIONS) {
            xFields.get(action[0]).setText(String.valueOf(d[i][0]));
            yFields.get(action[0]).setText(String.valueOf(d[i][1]));
            i++;
        }
        radiusField.setText("120");
    }

    /** Overlay capture: the game stays visible, every tap is recorded. */
    /** package of the game the overlay is meant to sit on top of */
    private static final String GAME_PKG = "jp.pokemon.pokemonunite.charles";

    private void startCapture() {
        // 1. start the overlay service while this activity still has foreground rights
        // plain startService: this runs while the activity is still foreground, and
        // a foreground service would need startForeground() within 5 s (the overlay
        // window itself already keeps this process alive for the capture)
        android.content.Intent svc = new android.content.Intent(this, CaptureService.class);
        startService(svc);

        // 2. bring the GAME to the front. moveTaskToBack() is not enough: this app
        //    is usually launched from the launcher, so "back" lands on the home
        //    screen and the overlay covers it with no way into the game.
        android.content.Intent game = getPackageManager().getLaunchIntentForPackage(GAME_PKG);
        if (game != null) {
            game.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                    | android.content.Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            startActivity(game);
            finish();
        } else {
            Toast.makeText(this, "game not installed (" + GAME_PKG + ")", Toast.LENGTH_LONG).show();
            android.content.Intent stop = new android.content.Intent(this, CaptureService.class);
            stopService(stop);
            moveTaskToBack(true);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        // after a capture (or a manual save) show what is actually stored
        if (xFields.isEmpty()) return;
        loadExisting();
    }

    private void loadExisting() {
        File f = profileFile();
        if (!f.exists()) {
            loadDefaults();
            return;
        }
        try {
            String json = new String(java.nio.file.Files.readAllBytes(f.toPath()),
                    StandardCharsets.UTF_8);
            for (String[] action : ACTIONS) {
                String kx = "\"" + action[0] + "_x\"", ky = "\"" + action[0] + "_y\"";
                String vx = value(json, kx), vy = value(json, ky);
                if (vx != null) xFields.get(action[0]).setText(vx);
                if (vy != null) yFields.get(action[0]).setText(vy);
            }
            for (Map.Entry<String, android.widget.Spinner> e : bindSpinners.entrySet()) {
                String b = valueStr(json, "\"bind_" + e.getKey() + "\"");
                if (b != null) e.getValue().setSelection(indexOf(BIND_OPTIONS, b));
            }
            String r = value(json, "\"radius\"");
            if (r != null) radiusField.setText(r);
        } catch (Exception e) {
            loadDefaults();
        }
    }

    private static String value(String json, String key) {
        int i = json.indexOf(key);
        if (i < 0) return null;
        int colon = json.indexOf(':', i);
        int end = json.indexOf(',', colon);
        if (end < 0) end = json.indexOf('}', colon);
        if (colon < 0 || end < 0) return null;
        return json.substring(colon + 1, end).replaceAll("[^0-9-]", "").trim();
    }

    private static String valueStr(String json, String key) {
        int i = json.indexOf(key);
        if (i < 0) return null;
        int colon = json.indexOf(':', i);
        int q1 = json.indexOf('"', colon + 1);
        int q2 = json.indexOf('"', q1 + 1);
        if (colon < 0 || q1 < 0 || q2 < 0) return null;
        return json.substring(q1 + 1, q2);
    }

    private void save() {
        StringBuilder sb = new StringBuilder("{\n");
        boolean first = true;
        for (String[] action : ACTIONS) {
            String k = action[0];
            String vx = text(xFields.get(k)), vy = text(yFields.get(k));
            if (vx.isEmpty() || vy.isEmpty()) continue;
            if (!first) sb.append(",\n");
            sb.append("  \"").append(k).append("_x\": ").append(vx).append(",\n");
            sb.append("  \"").append(k).append("_y\": ").append(vy);
            first = false;
        }
        for (Map.Entry<String, android.widget.Spinner> e : bindSpinners.entrySet()) {
            Object sel = e.getValue().getSelectedItem();
            if (sel == null || "none".equals(sel.toString())) continue;
            if (!first) sb.append(",\n");
            sb.append("  \"bind_").append(e.getKey()).append("\": \"").append(sel).append("\"");
            first = false;
        }

        String r = text(radiusField);
        if (!r.isEmpty()) {
            if (!first) sb.append(",\n");
            sb.append("  \"radius\": ").append(r);
        }
        sb.append("\n}\n");

        try (FileOutputStream out = new FileOutputStream(profileFile())) {
            out.write(sb.toString().getBytes(StandardCharsets.UTF_8));
            Toast.makeText(this, "Saved — sync it on the host", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "Save failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static String text(EditText e) {
        return e.getText().toString().trim();
    }
}
