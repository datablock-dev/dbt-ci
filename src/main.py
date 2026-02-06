import sys
from cli import arg_parser

def main():
    try:
        args = arg_parser()
        # Implement the main functionality here

        print(args)


    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)



if __name__ == "__main__":
    main()