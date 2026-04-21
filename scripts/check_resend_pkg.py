import traceback


def main():
    try:
        import importlib
        mod = importlib.import_module('resend')
        print('MODULE_FILE:', getattr(mod, '__file__', None))
        print('MODULE_VERSION:', getattr(mod, '__version__', None))
        print('HAS_Resend:', hasattr(mod, 'Resend'))
        print('HAS_Client:', hasattr(mod, 'Client'))
        print('HAS_ResendClient:', hasattr(mod, 'ResendClient'))
        public = [name for name in dir(mod) if name[0].isupper()]
        print('PUBLIC_EXPORTS_COUNT:', len(public))
        print('PUBLIC_EXPORTS_SAMPLE:', public[:50])
    except Exception:
        traceback.print_exc()


if __name__ == '__main__':
    main()
