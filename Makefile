CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -pthread
CPPFLAGS ?= -I. -Ilib
LDFLAGS ?=
LDLIBS ?=

TARGET := run_graph_orientation
SRC := run_graph_orientation.cpp
OBJ := $(SRC:.cpp=.o)
DEP := $(OBJ:.o=.d)

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJ)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)

%.o: %.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@

run: $(TARGET)
	./$(TARGET)

clean:
	$(RM) $(TARGET) $(OBJ) $(DEP)

-include $(DEP)
