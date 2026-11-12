from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    from dc_assistant.app import main

    main()
