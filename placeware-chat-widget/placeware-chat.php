<?php
/**
 * Plugin Name: Placeware Chat Widget
 * Description: RAG Chatbot Widget for Placeware (SaaS Connected).
 * Version: 1.0.1
 * Author: Placeware
 * Text Domain: placeware-chat
 */

if (!defined('ABSPATH')) {
    exit;
}

class Placeware_Chat_Widget {
    public function __construct() {
        add_action('wp_enqueue_scripts', array($this, 'enqueue_assets'));
        add_action('wp_footer', array($this, 'render_widget'));
        add_action('admin_menu', array($this, 'add_admin_menu'));
        add_action('admin_init', array($this, 'register_settings'));
    }

    public function enqueue_assets() {
        wp_enqueue_style(
            'placeware-widget-css',
            plugin_dir_url(__FILE__) . 'assets/css/widget.css',
            array(),
            '1.0.1'
        );
        wp_enqueue_script(
            'placeware-widget-js',
            plugin_dir_url(__FILE__) . 'assets/js/widget.js',
            array(),
            '1.0.1',
            true
        );

        $api_url  = get_option('placeware_api_url', 'http://localhost:8000');
        $site_key = get_option('placeware_site_key', 'site_prod_abc123');

        wp_localize_script('placeware-widget-js', 'PlacewareConfig', array(
            'apiUrl'  => rtrim($api_url, '/'),
            'siteKey' => $site_key,
        ));
    }

    public function render_widget() {
        // Always render the mount point — JS uses PlacewareConfig.apiUrl at runtime
        ?>
        <div id="placeware-chat-root"></div>
        <?php
    }

    public function add_admin_menu() {
        add_options_page(
            'Placeware Chat',
            'Placeware Chat',
            'manage_options',
            'placeware-chat',
            array($this, 'render_settings_page')
        );
    }

    public function register_settings() {
        register_setting('placeware_chat_options', 'placeware_api_url');
        register_setting('placeware_chat_options', 'placeware_site_key');
    }

    public function render_settings_page() {
        ?>
        <div class="wrap">
            <h1>Placeware Chat Configuration</h1>
            <form method="post" action="options.php">
                <?php
                settings_fields('placeware_chat_options');
                do_settings_sections('placeware_chat_options');
                ?>
                <table class="form-table">
                    <tr valign="top">
                        <th scope="row">API Base URL</th>
                        <td>
                            <input type="text" name="placeware_api_url" value="<?php echo esc_attr(get_option('placeware_api_url', 'http://localhost:8000')); ?>" class="regular-text" />
                            <p class="description">e.g., http://localhost:8000 (must be reachable from the visitor's browser)</p>
                        </td>
                    </tr>
                    <tr valign="top">
                        <th scope="row">Site Key</th>
                        <td>
                            <input type="text" name="placeware_site_key" value="<?php echo esc_attr(get_option('placeware_site_key', 'site_prod_abc123')); ?>" class="regular-text" />
                            <p class="description">
                                Must match one of the keys in <code>WIDGET_SITE_KEYS</code> in your backend <code>.env</code> file.<br>
                                Default value: <code>site_prod_abc123</code> (matches the current backend configuration).
                            </p>
                        </td>
                    </tr>
                </table>
                <?php submit_button(); ?>
            </form>
        </div>
        <?php
    }
}

new Placeware_Chat_Widget();
