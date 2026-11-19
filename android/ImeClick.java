import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Constructor;

public final class ImeClick {
    private static final class Candidate {
        AccessibilityNodeInfo node;
        long area = Long.MAX_VALUE;
        int depth = -1;
    }

    private static void find(AccessibilityNodeInfo node, int x, int y, int depth, Candidate best) {
        if (node == null || depth > 40) return;
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        if (!bounds.isEmpty() && !bounds.contains(x, y)) return;
        if (node.isVisibleToUser() && node.isClickable() && node.isFocusable() && node.isEnabled()
                && bounds.width() > 0 && bounds.height() > 0 && bounds.contains(x, y)) {
            long area = (long) bounds.width() * bounds.height();
            if (area < best.area || (area == best.area && depth > best.depth)) {
                if (best.node != null) best.node.recycle();
                best.node = AccessibilityNodeInfo.obtain(node);
                best.area = area;
                best.depth = depth;
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                find(child, x, y, depth + 1, best);
                child.recycle();
            }
        }
    }

    private static void injectKey(UiAutomation automation, int keyCode) {
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keyCode, 0);
        down.setSource(InputDevice.SOURCE_DPAD);
        automation.injectInputEvent(down, true);
        KeyEvent up = new KeyEvent(now, now, KeyEvent.ACTION_UP, keyCode, 0);
        up.setSource(InputDevice.SOURCE_DPAD);
        automation.injectInputEvent(up, true);
    }

    private static void injectTap(UiAutomation automation, int x, int y) {
        long downTime = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN, x, y, 0);
        down.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        automation.injectInputEvent(down, true);
        down.recycle();
        MotionEvent up = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, x, y, 0);
        up.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        automation.injectInputEvent(up, true);
        up.recycle();
    }

    private static String handleClick(UiAutomation automation, int x, int y, boolean pointerSelection, boolean inject) {
        boolean foundIme = false;
        Candidate candidate = new Candidate();
        try {
            for (AccessibilityWindowInfo window : automation.getWindows()) {
                if (window.getType() != AccessibilityWindowInfo.TYPE_INPUT_METHOD
                        || window.getDisplayId() != 0) continue;
                AccessibilityNodeInfo root = window.getRoot();
                if (root == null) continue;
                foundIme = true;
                try {
                    find(root, x, y, 0, candidate);
                } finally {
                    root.recycle();
                }
            }
            if (!foundIme) {
                if (inject && x >= 0 && y >= 0) {
                    injectTap(automation, x, y);
                }
                return "no_ime";
            }
            if (!pointerSelection) {
                if (inject) {
                    injectKey(automation, KeyEvent.KEYCODE_DPAD_CENTER);
                }
                return "dpad";
            }
            if (candidate.node != null && (candidate.node.isFocused()
                    || (candidate.node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                        && candidate.node.refresh() && candidate.node.isFocused()))) {
                if (inject) {
                    injectKey(automation, KeyEvent.KEYCODE_DPAD_CENTER);
                }
                return "focused";
            }
            return "miss";
        } finally {
            if (candidate.node != null) candidate.node.recycle();
        }
    }

    public static void main(String[] args) {
        HandlerThread thread = null;
        UiAutomation automation = null;
        boolean daemon = args.length == 1 && "--daemon".equals(args[0]);
        String outcome = "unavailable";
        try {
            if (!daemon && args.length != 2) throw new IllegalArgumentException();
            int singleX = -1;
            int singleY = -1;
            if (!daemon) {
                singleX = Integer.parseInt(args[0]);
                singleY = Integer.parseInt(args[1]);
                if (singleX < 0 || singleY < 0) throw new IllegalArgumentException();
            }

            thread = new HandlerThread("ImeClick");
            thread.start();
            Class<?> connectionType = Class.forName("android.app.IUiAutomationConnection");
            Object connection = Class.forName("android.app.UiAutomationConnection")
                    .getDeclaredConstructor().newInstance();
            Constructor<UiAutomation> constructor =
                    UiAutomation.class.getDeclaredConstructor(Looper.class, connectionType);
            automation = constructor.newInstance(thread.getLooper(), connection);
            UiAutomation.class.getDeclaredMethod("connectWithTimeout", int.class, long.class)
                    .invoke(automation, 1, 2000L);

            AccessibilityServiceInfo info = automation.getServiceInfo();
            info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                    | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
            automation.setServiceInfo(info);

            if (daemon) {
                System.out.println("ready");
                System.out.flush();
                BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.trim();
                    if (line.isEmpty()) continue;
                    if ("quit".equals(line)) break;
                    String[] parts = line.split("\\s+");
                    if (parts.length < 2) {
                        System.out.println("invalid");
                        System.out.flush();
                        continue;
                    }
                    int x = Integer.parseInt(parts[0]);
                    int y = Integer.parseInt(parts[1]);
                    boolean ptrSel = parts.length < 3 || !"0".equals(parts[2]);
                    System.out.println(handleClick(automation, x, y, ptrSel, true));
                    System.out.flush();
                }
                return;
            }

            String res = handleClick(automation, singleX, singleY, true, false);
            outcome = "no_ime".equals(res) ? "unavailable" : res;
        } catch (Exception ignored) {
            outcome = "unavailable";
        } finally {
            if (automation != null) {
                try { UiAutomation.class.getDeclaredMethod("disconnect").invoke(automation); }
                catch (Exception ignored) {}
            }
            if (thread != null) thread.quitSafely();
        }
        if (!daemon) {
            System.out.println(outcome);
        }
    }
}
