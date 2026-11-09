import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from keepquiet.cli import main
    raise SystemExit(main())
