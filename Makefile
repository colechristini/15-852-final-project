CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -pthread
CPPFLAGS ?= -I. -Ilib
LDFLAGS ?=
LDLIBS ?=

TARGET := run_graph_orientation
INSTRUMENTED_TARGET := run_graph_orientation_instrumented
SRC := run_graph_orientation.cpp
OBJ := $(SRC:.cpp=.o)
INSTRUMENTED_OBJ := $(SRC:.cpp=.instrumented.o)
DEP := $(OBJ:.o=.d) $(INSTRUMENTED_OBJ:.o=.d)

.PHONY: all clean instrumented run

all: $(TARGET)

instrumented: $(INSTRUMENTED_TARGET)

$(TARGET): $(OBJ)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)

$(INSTRUMENTED_TARGET): $(INSTRUMENTED_OBJ)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)

%.o: %.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@

%.instrumented.o: %.cpp
	$(CXX) $(CPPFLAGS) -DINSTRUMENT $(CXXFLAGS) -MMD -MP -c $< -o $@

run: $(TARGET)
	./$(TARGET)

clean:
	$(RM) $(TARGET) $(INSTRUMENTED_TARGET) $(OBJ) $(INSTRUMENTED_OBJ) $(DEP)

-include $(DEP)
